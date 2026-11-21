"""Slice A, feature 2: consume the `duty-rota` topic and write it to the database.

Usage:
    pip install confluent-kafka "psycopg[binary]"
    python load/consumer.py

What it does, per message (see docs/data-contract.md):
    1. decode + validate        -> bad message: log it, skip it, never crash
    2. upsert into duty_rota    -> same message twice is harmless
    3. commit the Kafka offset  -> ONLY after the database write succeeded
"""

import json
import logging
import os
import signal
import time
from datetime import datetime, timezone

# --- Configuration -----------------------------------------------------------

BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092")
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://pharma:pharma@localhost:5432/pharmacy"
)
TOPIC = "duty-rota"
# The group id is the consumer's identity for Kafka: committed offsets are stored per
# group. Change it and the consumer re-reads the whole topic (you saw this by hand).
GROUP_ID = os.environ.get("GROUP_ID", "duty-rota-consumer")

ALLOWED_SOURCES = {"simulator", "manual", "scraper"}

log = logging.getLogger("duty-rota-consumer")


# --- Step 1: validation (pure function, no Kafka, no database) ---------------

class BadMessage(Exception):
    """The message breaks the data contract. It will be logged and skipped."""


def parse_utc(value, field):
    """Parse '2026-11-20T19:00:00Z'. The contract demands UTC with a trailing Z."""
    if not isinstance(value, str) or not value.endswith("Z"):
        raise BadMessage(f"{field} must be an ISO 8601 UTC string ending with Z, got {value!r}")
    try:
        # fromisoformat does not accept "Z" on every Python version, so swap it for +00:00.
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError:
        raise BadMessage(f"{field} is not a valid timestamp: {value!r}")


def validate(raw_value):
    """Turn the raw bytes of a Kafka message into a clean dict, or raise BadMessage."""
    if raw_value is None:
        raise BadMessage("empty message")

    try:
        data = json.loads(raw_value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BadMessage(f"not valid UTF-8 JSON: {exc}")

    if not isinstance(data, dict):
        raise BadMessage(f"expected a JSON object, got {type(data).__name__}")

    missing = {"pharmacy_id", "starts_at", "ends_at", "source"} - data.keys()
    if missing:
        raise BadMessage(f"missing fields: {sorted(missing)}")

    pharmacy_id = data["pharmacy_id"]
    # bool is a subclass of int in Python, so True would sneak through without this check.
    if not isinstance(pharmacy_id, int) or isinstance(pharmacy_id, bool):
        raise BadMessage(f"pharmacy_id must be an integer, got {pharmacy_id!r}")

    starts_at = parse_utc(data["starts_at"], "starts_at")
    ends_at = parse_utc(data["ends_at"], "ends_at")
    if ends_at <= starts_at:
        raise BadMessage("ends_at must be after starts_at")

    if data["source"] not in ALLOWED_SOURCES:
        raise BadMessage(f"source must be one of {sorted(ALLOWED_SOURCES)}, got {data['source']!r}")

    return {
        "pharmacy_id": pharmacy_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "source": data["source"],
    }


# --- Step 2: database write --------------------------------------------------

# The upsert from the contract: if (pharmacy_id, starts_at) already exists, update ends_at.
UPSERT_SQL = """
INSERT INTO duty_rota (pharmacy_id, starts_at, ends_at, source)
VALUES (%(pharmacy_id)s, %(starts_at)s, %(ends_at)s, %(source)s)
ON CONFLICT (pharmacy_id, starts_at) DO UPDATE SET ends_at = EXCLUDED.ends_at
"""


def connect_db():
    import psycopg
    # autocommit: each message is a single statement, so it is its own transaction.
    return psycopg.connect(DATABASE_URL, autocommit=True)


# --- Step 3: the loop --------------------------------------------------------

running = True


def stop(signum, frame):
    global running
    running = False


def handle(msg, conn):
    """Process one message. Returns normally when the message is DONE (written or skipped).

    Raises psycopg.OperationalError when the database is unavailable: that is NOT the
    message's fault, so the caller must retry instead of skipping.
    """
    import psycopg

    where = f"partition={msg.partition()} offset={msg.offset()} key={msg.key()!r}"
    try:
        row = validate(msg.value())
        conn.execute(UPSERT_SQL, row)
        log.info("stored  %s -> pharmacy %s on duty %s .. %s",
                 where, row["pharmacy_id"], row["starts_at"].isoformat(), row["ends_at"].isoformat())
    except BadMessage as exc:
        log.warning("SKIPPED %s: %s | raw=%r", where, exc, msg.value())
    except psycopg.errors.ForeignKeyViolation:
        # The contract says pharmacy_id must exist. The database enforces it for us,
        # so we do not need a separate SELECT: we just handle the refusal.
        log.warning("SKIPPED %s: pharmacy_id does not exist | raw=%r", where, msg.value())


def main():
    import psycopg
    from confluent_kafka import Consumer, KafkaError

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    consumer = Consumer({
        "bootstrap.servers": BOOTSTRAP_SERVERS,
        "group.id": GROUP_ID,
        # Used only when the group has NO committed offset yet (first run, or new group id).
        "auto.offset.reset": "earliest",
        # We commit by hand, after the database write. This is what gives
        # at-least-once delivery: a crash between write and commit means a replay,
        # which the idempotent upsert makes harmless.
        "enable.auto.commit": False,
    })
    consumer.subscribe([TOPIC])
    conn = connect_db()
    log.info("Consuming %r as group %r (Ctrl+C to stop)", TOPIC, GROUP_ID)

    try:
        while running:
            msg = consumer.poll(1.0)  # wait up to 1 s for a message
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    log.error("Kafka error: %s", msg.error())
                continue

            # Retry the SAME message until the database accepts it or we are told to stop.
            while running:
                try:
                    handle(msg, conn)
                    # Done (stored or skipped as bad): move our position past this message.
                    # Skipped messages are committed too, otherwise a bad message would
                    # be replayed forever after every restart.
                    consumer.commit(message=msg, asynchronous=False)
                    break
                except psycopg.OperationalError as exc:
                    log.error("Database unavailable (%s). Retrying in 3 s, offset NOT committed.", exc)
                    time.sleep(3)
                    try:
                        conn.close()
                        conn = connect_db()
                    except psycopg.OperationalError:
                        pass
    finally:
        log.info("Shutting down.")
        consumer.close()  # leaves the group cleanly so partitions are reassigned quickly
        conn.close()


if __name__ == "__main__":
    main()




