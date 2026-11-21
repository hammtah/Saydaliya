"""Slice A, feature 4: rota simulator. Produces fake `duty-rota` messages.

Usage:
    pip install confluent-kafka "psycopg[binary]"
    python load/simulator.py burst --count 8       # put 8 random pharmacies on duty tonight
    python load/simulator.py live                  # keep switching pharmacies on and off
    python load/simulator.py live --interval 2 --bad-rate 0.2   # faster, with some garbage

Pharmacy ids are read from the database so messages point to pharmacies that exist.
No database at hand? Pass --ids 1,2,3,4,5 instead.

Messages follow docs/data-contract.md: JSON, UTC timestamps ending with Z,
source "simulator", and the pharmacy_id as the Kafka key.
"""

import argparse
import json
import os
import random
import signal
import time
from datetime import datetime, timedelta, timezone

BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092")
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://pharma:pharma@localhost:5432/pharmacy"
)
TOPIC = "duty-rota"


# --- Building messages (pure functions, easy to test) ------------------------

def iso_utc(dt):
    """Contract format: ISO 8601 in UTC with a trailing Z, no microseconds."""
    return dt.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def duty_message(pharmacy_id, starts_at, ends_at):
    return {
        "pharmacy_id": pharmacy_id,
        "starts_at": iso_utc(starts_at),
        "ends_at": iso_utc(ends_at),
        "source": "simulator",
    }


def tonight_window(now):
    """A window that is ALREADY running, so the pharmacy shows up in v_open_now immediately."""
    starts_at = now - timedelta(minutes=5)
    ends_at = now + timedelta(hours=random.randint(6, 10))
    return starts_at, ends_at


def bad_message():
    """Deliberate garbage, to watch the consumer skip it instead of crashing."""
    return random.choice([
        b"this is not json",
        b'{"pharmacy_id": 1}',
        b'{"pharmacy_id": 999999, "starts_at": "2026-01-01T00:00:00Z", '
        b'"ends_at": "2026-01-02T00:00:00Z", "source": "simulator"}',
        b'{"pharmacy_id": 1, "starts_at": "2026-01-02T00:00:00Z", '
        b'"ends_at": "2026-01-01T00:00:00Z", "source": "simulator"}',
    ])


# --- Sending -----------------------------------------------------------------

def on_delivery(err, msg):
    """Called by the producer (from poll/flush) when Kafka confirms or rejects a message."""
    if err is not None:
        print(f"  DELIVERY FAILED key={msg.key()!r}: {err}")
    else:
        print(f"  delivered   key={msg.key().decode()} -> partition {msg.partition()} offset {msg.offset()}")


def send(producer, pharmacy_id, payload):
    # The key decides the partition: same pharmacy -> same partition -> messages stay in order.
    producer.produce(
        TOPIC,
        key=str(pharmacy_id).encode(),
        value=payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8"),
        on_delivery=on_delivery,
    )
    # produce() only queues the message. poll(0) lets the producer run delivery callbacks.
    producer.poll(0)


def load_pharmacy_ids():
    import psycopg
    with psycopg.connect(DATABASE_URL) as conn:
        return [row[0] for row in conn.execute("SELECT id FROM pharmacies ORDER BY id")]


# --- Modes -------------------------------------------------------------------

def burst(producer, ids, count):
    """Put `count` random pharmacies on duty tonight, then exit."""
    now = datetime.now(timezone.utc)
    for pharmacy_id in random.sample(ids, min(count, len(ids))):
        starts_at, ends_at = tonight_window(now)
        message = duty_message(pharmacy_id, starts_at, ends_at)
        print(f"on duty  pharmacy {pharmacy_id}: {message['starts_at']} .. {message['ends_at']}")
        send(producer, pharmacy_id, message)


stop = False


def handle_stop(signum, frame):
    global stop
    stop = True


def live(producer, ids, interval, bad_rate):
    """Every `interval` seconds, switch a random pharmacy on or off, until Ctrl+C.

    Switching OFF reuses the contract's upsert: same (pharmacy_id, starts_at),
    but ends_at = now. The window closes immediately, no special 'off' message needed.
    """
    signal.signal(signal.SIGINT, handle_stop)
    on_duty = {}  # pharmacy_id -> starts_at of its currently running window
    print("Live mode. Ctrl+C to stop.")

    while not stop:
        now = datetime.now(timezone.utc)

        if random.random() < bad_rate:
            print("sending GARBAGE")
            send(producer, random.choice(ids), bad_message())
        else:
            pharmacy_id = random.choice(ids)
            if pharmacy_id in on_duty and random.random() < 0.5:
                starts_at = on_duty.pop(pharmacy_id)
                print(f"OFF      pharmacy {pharmacy_id}")
                send(producer, pharmacy_id, duty_message(pharmacy_id, starts_at, now))
            elif pharmacy_id not in on_duty:
                starts_at, ends_at = tonight_window(now)
                on_duty[pharmacy_id] = starts_at
                print(f"ON       pharmacy {pharmacy_id}")
                send(producer, pharmacy_id, duty_message(pharmacy_id, starts_at, ends_at))

        time.sleep(interval)


def main():
    from confluent_kafka import Producer

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("mode", choices=["burst", "live"])
    parser.add_argument("--count", type=int, default=8, help="burst: how many pharmacies")
    parser.add_argument("--interval", type=float, default=3.0, help="live: seconds between messages")
    parser.add_argument("--bad-rate", type=float, default=0.0, help="live: share of garbage messages, 0 to 1")
    parser.add_argument("--ids", help="comma-separated pharmacy ids (skips the database)")
    args = parser.parse_args()

    ids = [int(x) for x in args.ids.split(",")] if args.ids else load_pharmacy_ids()
    if not ids:
        raise SystemExit("No pharmacies found. Did you run the seed?")

    producer = Producer({
        "bootstrap.servers": BOOTSTRAP_SERVERS,
        "acks": "all",  # wait until the broker has stored the message before calling it delivered
    })

    try:
        if args.mode == "burst":
            burst(producer, ids, args.count)
        else:
            live(producer, ids, args.interval, args.bad_rate)
    finally:
        # flush() blocks until every queued message is delivered. Without it, a script
        # that exits right after produce() can silently lose its last messages.
        remaining = producer.flush(10)
        if remaining:
            print(f"WARNING: {remaining} message(s) were not delivered")


if __name__ == "__main__":
    main()
