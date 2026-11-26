"""Test the exact demo SQL on a NEW isolated Compose project (PostGIS only).

Usage: python -B tests/test_demo_24h.py
Never connects to the developer database. Reuses Step 0 isolation/cleanup guards.
"""

import argparse
import json
import re
import sys
import tempfile
import time
import uuid

from test_step0 import ROOT, Step0Checks

IDS = (-24001, -24002, -24003)
ADD = ROOT / "demo/add_24h.sql"
REMOVE = ROOT / "demo/remove_24h.sql"


class DemoChecks(Step0Checks):
    def other_rows(self):
        return self.conn.execute("""
            SELECT jsonb_build_object(
              'pharmacies', (SELECT jsonb_agg(to_jsonb(p) ORDER BY id)
                FROM pharmacies p WHERE id NOT IN (-24001,-24002,-24003)),
              'duty_rota', (SELECT jsonb_agg(to_jsonb(d) ORDER BY id)
                FROM duty_rota d WHERE pharmacy_id NOT IN (-24001,-24002,-24003)),
              'confirmations', (SELECT jsonb_agg(to_jsonb(c) ORDER BY id)
                FROM confirmations c WHERE pharmacy_id NOT IN (-24001,-24002,-24003)))
        """).fetchone()[0]

    def assert_others_unchanged(self):
        assert self.other_rows() == self.original_other_rows, "Unrelated rows changed"

    def demo_rows(self):
        return self.conn.execute("""
            SELECT p.id,
                (SELECT count(*) FROM duty_rota d WHERE d.pharmacy_id=p.id),
                (SELECT count(*) FROM confirmations c WHERE c.pharmacy_id=p.id)
            FROM pharmacies p WHERE id IN (-24001,-24002,-24003) ORDER BY id
        """).fetchall()

    def start_database(self):
        self.compose("up", "-d", "--wait", "--wait-timeout", "120", "db")
        self.assert_owned()
        container_id = self.compose("ps", "-q", "db").stdout.strip()
        details = json.loads(self.run("docker", "inspect", container_id).stdout)[0]
        bindings = details["NetworkSettings"]["Ports"]["5432/tcp"]
        assert bindings and all(b["HostPort"] == self.env["POSTGRES_PORT"] for b in bindings)
        import psycopg
        # pg_isready via Unix socket can see the temporary init server before
        # PostGIS finishes initialization and restarts. Wait for real host TCP.
        deadline = time.monotonic() + 60
        while True:
            try:
                self.conn = psycopg.connect(
                    self.env["DATABASE_URL"], autocommit=True, connect_timeout=3
                )
                break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.5)
        assert self.conn.execute("SELECT to_regclass('pharmacies')").fetchone()[0] is None
        self.seed()  # Destructive seed is used ONLY on this new, test-owned database.
        assert not self.demo_rows()
        self.original_other_rows = self.other_rows()
        self.pass_check("isolated PostGIS initialized; demo IDs unused; no Kafka started")

    def execute(self):
        self.start_database()
        self.refuse_existing_project()

        self.sql_file(ADD)
        assert self.demo_rows() == [(-24003, 1, 0), (-24002, 1, 0), (-24001, 1, 0)]
        assert self.conn.execute("""
            SELECT pharmacy_id,
                ends_at-starts_at=interval '24 hours' AS duration_24h,
                starts_at<=now() AND now()<ends_at AS active
            FROM duty_rota WHERE pharmacy_id IN (-24001,-24002,-24003)
            ORDER BY pharmacy_id
        """).fetchall() == [(-24003, True, False), (-24002, False, True), (-24001, True, True)]
        assert self.conn.execute("""
            SELECT ends_at-starts_at=interval '12 hours'
            FROM duty_rota WHERE pharmacy_id=-24002
        """).fetchone() == (True,)
        self.assert_others_unchanged()
        self.pass_check("add: three dedicated pharmacies, one duty each, no confirmations, exact durations")

        limit = str(self.conn.execute("SELECT count(*) FROM pharmacies").fetchone()[0])
        for mode, expected in (("open", {-24001,-24002}), ("24h", {-24001})):
            output = self.run(sys.executable, "-B", "load/filters.py", mode, "--limit", limit).stdout
            listed = [int(value) for value in re.findall(r"^\s*(-?\d+)\s+", output, re.MULTILINE)]
            demo_ids = [value for value in listed if value in IDS]
            assert set(demo_ids) == expected and len(demo_ids) == len(expected), output
            print(f"FILTER {mode}: demo IDs={sorted(demo_ids)}, limit={limit}", flush=True)
            self.pass_check(f"{mode} CLI: expected demo cases appear once; expired absent")

        before = self.snapshot()  # Includes all rows AND sequence positions.
        repeated = self.sql_file(ADD, check=False)
        assert repeated.returncode == 3 and "pharmacies_pkey" in repeated.stderr, repeated.stderr
        assert self.snapshot() == before
        self.assert_others_unchanged()
        self.pass_check("second add refused (psql exit 3); all rows and sequence positions unchanged")

        self.sql_file(REMOVE)
        assert not self.demo_rows()
        assert self.conn.execute("SELECT count(*) FROM duty_rota WHERE pharmacy_id IN (-24001,-24002,-24003)").fetchone() == (0,)
        self.assert_others_unchanged()
        self.pass_check("remove: only the three demo pharmacies and their duties deleted")

        before = self.snapshot()
        self.sql_file(REMOVE)
        assert self.snapshot() == before
        self.pass_check("second remove succeeds with no effect, including sequence positions")

        # Recreate ONLY this test's demo records to test refusal after a report.
        self.sql_file(ADD)
        event_id = uuid.uuid4()
        self.conn.execute("""
            INSERT INTO confirmations(event_id,pharmacy_id,status,confirmed_at)
            VALUES (%s,-24001,'closed',now())
        """, (event_id,))
        before = self.snapshot()
        refused = self.sql_file(REMOVE, check=False)
        assert refused.returncode == 3 and "retrait refuse" in refused.stderr, refused.stderr
        assert self.snapshot() == before
        assert self.demo_rows() == [(-24003,1,0),(-24002,1,0),(-24001,1,1)]
        self.assert_others_unchanged()
        self.pass_check("remove after a confirmation refused (psql exit 3); entire dataset unchanged")

        # Remove only the event generated above; no unrelated confirmation is touched.
        deleted = self.conn.execute("""
            DELETE FROM confirmations WHERE event_id=%s AND pharmacy_id=-24001
        """, (event_id,)).rowcount
        assert deleted == 1
        self.sql_file(REMOVE)
        assert not self.demo_rows()
        self.assert_others_unchanged()
        assert self.conn.execute("SELECT count(*) FROM pharmacies").fetchone() == (20,)
        assert self.conn.execute("SELECT count(*) FROM duty_rota").fetchone() == (11,)
        assert self.conn.execute("SELECT count(*) FROM confirmations").fetchone() == (2,)
        self.pass_check("all unrelated pharmacy/duty/confirmation rows preserved byte-for-byte through all cases")
        print("NOTE: successful inserts advance duty/confirmation sequences normally; cleanup does not reset them.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="pharmacy-step0-test-" + uuid.uuid4().hex[:12])
    args = parser.parse_args()
    try:
        checks = DemoChecks(args.project)
    except ValueError as exc:
        parser.error(str(exc))
    failed = False
    with tempfile.TemporaryDirectory(prefix="pharmacy-step0-test-demo-") as temp:
        try:
            checks.prepare(temp)
            checks.execute()
        except Exception as exc:
            failed = True
            print(f"FAIL: {exc}", file=sys.stderr, flush=True)
            if checks.claimed:
                try:
                    print(checks.compose("logs", "--tail", "30", check=False).stdout, file=sys.stderr)
                except Exception as log_error:
                    print(f"Logs unavailable: {log_error}", file=sys.stderr)
        finally:
            try:
                checks.cleanup()
            except Exception as exc:
                failed = True
                print(f"FAIL cleanup (resources may remain for {checks.project}): {exc}", file=sys.stderr)
    print(f"{len(checks.passed)} checks passed; result={'FAIL' if failed else 'PASS'}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
