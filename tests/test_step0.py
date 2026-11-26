"""Integration checks. Always create a NEW, isolated Compose test project.

Usage: python -B tests/test_step0.py
Requires Docker, Compose and requirements.txt. No access to a developer database.
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import uuid

if not __debug__:
    raise SystemExit("REFUSED: run without -O/PYTHONOPTIMIZE; safety checks must stay enabled")

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
PROJECT_PATTERN = r"pharmacy-step0-test-[0-9a-f]{12}"


def require_test_project(project):
    if not re.fullmatch(PROJECT_PATTERN, project):
        raise ValueError("REFUSED: project must be pharmacy-step0-test-<12 hex digits>")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Step0Checks:
    def __init__(self, project):
        require_test_project(project)  # Before any Docker command or database access.
        self.project = project
        self.env = os.environ.copy()
        for key in list(self.env):
            if key.startswith("COMPOSE_"):
                del self.env[key]
        db_port, kafka_port = free_port(), free_port()
        while kafka_port == db_port:
            kafka_port = free_port()
        self.env.update(
            POSTGRES_PORT=str(db_port), KAFKA_PORT=str(kafka_port),
            DATABASE_URL=f"postgresql://pharma:pharma@127.0.0.1:{db_port}/pharmacy",
            KAFKA_BOOTSTRAP=f"localhost:{kafka_port}",
            GROUP_ID=f"{project}-consumer", PYTHONDONTWRITEBYTECODE="1",
            PYTHONUNBUFFERED="1",
        )
        self.claimed = False
        self.baseline = {}
        self.conn = None
        self.passed = []

    def run(self, *args, input=None, check=True, timeout=180):
        result = subprocess.run(
            args, cwd=ROOT, env=self.env, input=input, text=True,
            encoding="utf-8", errors="replace", capture_output=True, timeout=timeout,
        )
        if check and result.returncode:
            raise RuntimeError(f"{' '.join(map(str, args))}\n{result.stdout}\n{result.stderr}")
        return result

    def compose_args(self, *args, override=None):
        require_test_project(self.project)
        command = ["docker", "compose", "--project-name", self.project,
                   "--env-file", str(self.empty_env), "-f", str(ROOT / "docker-compose.yml")]
        if override:
            command += ["-f", str(override)]
        return command + list(args)

    def compose(self, *args, override=None, **kwargs):
        return self.run(*self.compose_args(*args, override=override), **kwargs)

    def resources(self):
        return {
            "containers": set(self.run("docker", "ps", "-aq", "--no-trunc").stdout.split()),
            "volumes": set(self.run("docker", "volume", "ls", "-q").stdout.split()),
            "networks": set(self.run("docker", "network", "ls", "-q", "--no-trunc").stdout.split()),
        }

    def pass_check(self, description):
        self.passed.append(description)
        print(f"PASS: {description}", flush=True)

    def prepare(self, temp):
        self.temp = Path(temp)
        self.empty_env = self.temp / "empty.env"
        self.empty_env.write_text("# Test-owned environment; ignore repository .env\n", encoding="utf-8")
        config = json.loads(self.compose("--profile", "tools", "config", "--format", "json").stdout)
        assert config["name"] == self.project
        for kind in ("volumes", "networks"):
            for item in config.get(kind, {}).values():
                assert not item.get("external"), f"External {kind} forbidden"
                assert item["name"].startswith(self.project + "_"), f"Shared {kind} forbidden"
        for service in config["services"].values():
            assert not service.get("container_name"), "Fixed container names forbidden"
            for mount in service.get("volumes", []):
                if mount["type"] == "bind":
                    assert Path(mount["source"]).resolve() == (ROOT / "sql").resolve()
                    assert mount["read_only"], "Writable source bind forbidden"
        for service, variable in (("db", "POSTGRES_PORT"), ("kafka", "KAFKA_PORT")):
            ports = config["services"][service]["ports"]
            assert len(ports) == 1 and ports[0]["published"] == self.env[variable]
        advertised = config["services"]["kafka"]["environment"]["KAFKA_ADVERTISED_LISTENERS"]
        assert f"HOST://localhost:{self.env['KAFKA_PORT']}" in advertised

        self.baseline = self.resources()
        for kind, command in (("container", ("ps", "-aq")),
                              ("volume", ("volume", "ls", "-q")),
                              ("network", ("network", "ls", "-q"))):
            existing = self.run("docker", *command, "--filter",
                                f"label=com.docker.compose.project={self.project}").stdout.strip()
            assert not existing, f"REFUSED: {kind} resources already exist for this test project"
        names = set(self.run("docker", "ps", "-a", "--format", "{{.Names}}").stdout.split())
        assert not any(n.startswith(self.project + "-") for n in names), "Container name collision"
        assert not ({f"{self.project}_pgdata", f"{self.project}_kafka_data"} & self.baseline["volumes"])
        network_names = self.run("docker", "network", "ls", "--format", "{{.Name}}").stdout.split()
        assert f"{self.project}_default" not in network_names
        self.claimed = True  # This namespace was empty and the configuration is isolated.
        print(f"Test project: {self.project}; DB port {self.env['POSTGRES_PORT']}; "
              f"Kafka port {self.env['KAFKA_PORT']}", flush=True)
        self.pass_check("test-only project, resources and advertised port guards")

    def assert_owned(self):
        require_test_project(self.project)
        assert self.claimed, "REFUSED: test namespace not claimed"
        containers = self.run("docker", "ps", "-aq", "--filter",
                              f"label=com.docker.compose.project={self.project}").stdout.split()
        if containers:
            for item in json.loads(self.run("docker", "inspect", *containers).stdout):
                labels = item["Config"]["Labels"]
                assert labels["com.docker.compose.project"] == self.project
                assert item["Id"] not in self.baseline["containers"]
                for mount in item["Mounts"]:
                    if mount["Type"] == "volume":
                        assert mount["Name"] not in self.baseline["volumes"], "Pre-existing volume attached"

    def start(self):
        # Default up automatically starts kafka-init, which waits for Kafka's healthcheck.
        self.compose("up", "-d", timeout=240)
        self.compose("wait", "kafka-init", timeout=120)
        self.compose("up", "-d", "--wait", "--wait-timeout", "120", "db", "kafka")
        self.assert_owned()
        import psycopg
        db_container = self.compose("ps", "-q", "db").stdout.strip()
        details = json.loads(self.run("docker", "inspect", db_container).stdout)[0]
        bindings = details["NetworkSettings"]["Ports"]["5432/tcp"]
        assert all(b["HostPort"] == self.env["POSTGRES_PORT"] for b in bindings)
        self.conn = psycopg.connect(self.env["DATABASE_URL"], autocommit=True)
        assert self.conn.execute("SELECT to_regclass('pharmacies')").fetchone()[0] is None
        self.pass_check("healthy services, automatic topics, initially empty database")

    def refuse_existing_project(self):
        result = self.run(sys.executable, "-B", "tests/test_step0.py", "--project",
                          self.project, check=False)
        assert result.returncode != 0 and "resources already exist" in result.stderr
        self.assert_owned()
        self.pass_check("a second runner refuses this already-used test project before changing it")

    def seed(self):
        self.assert_owned()
        output = self.compose("--profile", "tools", "run", "--rm", "seed").stdout
        positions = [output.index("Running /sql/" + p.name) for p in sorted((ROOT / "sql").glob("*.sql"))]
        assert positions == sorted(positions), output
        assert self.conn.execute("SELECT count(*) FROM pharmacies").fetchone()[0] == 20
        assert self.conn.execute("SELECT count(*) FROM duty_rota").fetchone()[0] == 11
        assert self.conn.execute("SELECT count(*) FROM confirmations").fetchone()[0] == 2
        assert not self.conn.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name='pharmacies' AND column_name='is_24h'"
        ).fetchone()

    def topics(self):
        from confluent_kafka.admin import AdminClient
        for _ in range(2):
            self.compose("run", "--rm", "kafka-init")
        metadata = AdminClient({"bootstrap.servers": self.env["KAFKA_BOOTSTRAP"]}).list_topics(timeout=15)
        for name in ("duty-rota", "confirmations"):
            topic = metadata.topics[name]
            assert not topic.error and len(topic.partitions) == 3
            assert all(len(p.replicas) == 1 for p in topic.partitions.values())
        assert all(b.port == int(self.env["KAFKA_PORT"]) for b in metadata.brokers.values())
        self.pass_check("both topics: 3 partitions, replication 1, repeated creation and host metadata")

    def sql_file(self, path, check=True):
        self.assert_owned()
        return self.compose("exec", "-T", "db", "psql", "-U", "pharma", "-d", "pharmacy",
                            "-v", "ON_ERROR_STOP=1", input=path.read_text(encoding="utf-8"), check=check)

    def snapshot(self):
        return self.conn.execute("""
            SELECT jsonb_build_object(
              'pharmacies', (SELECT jsonb_agg(to_jsonb(p) - 'is_24h' ORDER BY id) FROM pharmacies p),
              'duty_rota', (SELECT jsonb_agg(to_jsonb(d) ORDER BY id) FROM duty_rota d),
              'confirmations', (SELECT jsonb_agg(to_jsonb(c) ORDER BY id) FROM confirmations c),
              'sequences', jsonb_build_array(
                (SELECT last_value FROM pharmacies_id_seq),
                (SELECT last_value FROM duty_rota_id_seq),
                (SELECT last_value FROM confirmations_id_seq)))
        """).fetchone()[0]

    def legacy_upgrade(self):
        for path in sorted((ROOT / "sql").glob("0[1-5]_*.sql")):
            self.sql_file(path)
        self.conn.execute("""
            INSERT INTO pharmacies (name,address,phone,osm_id,is_24h,geom)
            VALUES ('FAKE legacy sentinel','Legacy address','000','node/900000099',true,
                    ST_SetSRID(ST_MakePoint(-7.62,33.59),4326)::geography)
        """)
        self.conn.execute("""
            INSERT INTO duty_rota (pharmacy_id,starts_at,ends_at,source)
            SELECT id,now()-interval '1 hour',now()+interval '11 hours','manual'
            FROM pharmacies WHERE osm_id='node/900000099'
        """)
        self.conn.execute("""
            INSERT INTO confirmations (event_id,pharmacy_id,status,confirmed_at)
            SELECT gen_random_uuid(),id,'open',now()-interval '5 minutes'
            FROM pharmacies WHERE osm_id='node/900000099'
        """)
        before = self.snapshot()
        migration = ROOT / "sql/06_open_now_without_is_24h.sql"
        # An unexpected dependent view must make DROP VIEW fail, not cascade-delete it.
        self.conn.execute("CREATE VIEW step0_dependency AS SELECT * FROM v_open_now")
        failure = self.sql_file(migration, check=False)
        assert failure.returncode != 0 and self.snapshot() == before
        assert self.conn.execute("SELECT to_regclass('step0_dependency')").fetchone()[0]
        assert self.conn.execute("SELECT is_24h FROM pharmacies LIMIT 1").fetchone() is not None
        self.conn.execute("DROP VIEW step0_dependency")
        self.sql_file(migration)
        assert self.snapshot() == before, "Migration changed existing rows or sequences"
        self.sql_file(migration)  # Migration is also safe to reapply.
        assert self.snapshot() == before
        assert not self.conn.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name='pharmacies' AND column_name='is_24h'"
        ).fetchone()
        self.pass_check("01-05 populated database -> 06 alone: rows/sequences preserved; no CASCADE; repeatable")

    def filter_rules(self):
        spec = importlib.util.spec_from_file_location("step0_filters", ROOT / "load/filters.py")
        filters = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(filters)
        params = {"lon": -7.62, "lat": 33.59, "limit": 100}
        def ids(conn, mode):
            return [r[0] for r in conn.execute(filters.build_query(mode), params)]
        opened, full_day = ids(self.conn, "open"), ids(self.conn, "24h")
        assert 2 in opened and 2 in full_day
        assert 5 in opened and 5 not in full_day
        assert 9 not in opened and 9 not in full_day
        assert self.conn.execute(
            "SELECT pharmacy_id,ends_at-starts_at=interval '24 hours' FROM duty_rota WHERE pharmacy_id IN (2,5,9) ORDER BY pharmacy_id"
        ).fetchall() == [(2, True), (5, False), (9, True)]
        assert self.conn.execute("SELECT count(*) FROM confirmations WHERE pharmacy_id IN (2,5,9)").fetchone()[0] == 0
        self.pass_check("24h active in both filters; 12h active only Open now; expired in neither")

        import psycopg
        conn = psycopg.connect(self.env["DATABASE_URL"])
        try:
            # Dedicated case: exactly two active windows, 12h and 24h, no reports.
            mixed_id = conn.execute("""
                INSERT INTO pharmacies(name,address,geom)
                VALUES ('FAKE mixed 12h and 24h','Isolated test only',
                        ST_SetSRID(ST_MakePoint(-7.62,33.59),4326)::geography)
                RETURNING id
            """).fetchone()[0]
            conn.execute("""
                INSERT INTO duty_rota(pharmacy_id,starts_at,ends_at,source) VALUES
                  (%s,now()-interval '1 hour',now()+interval '11 hours','manual'),
                  (%s,now()-interval '2 hours',now()+interval '22 hours','manual')
            """, (mixed_id, mixed_id))
            assert conn.execute("""
                SELECT count(*),
                       count(*) FILTER (WHERE ends_at-starts_at=interval '12 hours'),
                       count(*) FILTER (WHERE ends_at-starts_at=interval '24 hours')
                FROM duty_rota
                WHERE pharmacy_id=%s AND starts_at<=now() AND now()<ends_at
            """, (mixed_id,)).fetchone() == (2, 1, 1)
            assert conn.execute("""
                SELECT id,has_active_24h_duty FROM v_open_now WHERE id=%s
            """, (mixed_id,)).fetchall() == [(mixed_id, True)]
            assert ids(conn, "open").count(mixed_id) == 1
            assert ids(conn, "24h").count(mixed_id) == 1
            self.pass_check("exactly two active duties (12h and 24h): one view row, has_active_24h_duty=true, one row in each filter")

            conn.execute("""
                INSERT INTO duty_rota(pharmacy_id,starts_at,ends_at,source) VALUES
                  (2,now()-interval '1 hour',now()+interval '2 hours','manual'),
                  (2,now()-interval '3 hours',now()+interval '21 hours','manual'),
                  (5,now()-interval '26 hours',now()-interval '2 hours','manual'),
                  (5,now()+interval '1 hour',now()+interval '25 hours','manual'),
                  (9,now()+interval '1 hour',now()+interval '25 hours','manual'),
                  (18,now(),now()+interval '12 hours','manual'),
                  (19,now()-interval '12 hours',now(),'manual')
            """)
            assert ids(conn, "open").count(2) == 1 and ids(conn, "24h").count(2) == 1
            assert 5 in ids(conn, "open") and 5 not in ids(conn, "24h")
            assert 18 in ids(conn, "open") and 19 not in ids(conn, "open")
            def confirm(status, offset, pharmacy=2):
                conn.execute("""
                    INSERT INTO confirmations(event_id,pharmacy_id,status,confirmed_at)
                    VALUES (%s,%s,%s,now()+%s::interval)
                """, (uuid.uuid4(), pharmacy, status, offset))
            confirm("closed", "-61 minutes")
            assert 2 in ids(conn, "open")
            confirm("closed", "-60 minutes")
            assert 2 in ids(conn, "open")
            confirm("closed", "-30 minutes")
            assert 2 not in ids(conn, "open") and 2 not in ids(conn, "24h")
            confirm("open", "-40 minutes")
            assert 2 not in ids(conn, "open")  # An older open does not cancel closed.
            confirm("open", "-20 minutes")
            assert 2 in ids(conn, "open") and 2 in ids(conn, "24h")
            confirm("closed", "-20 minutes")
            assert 2 not in ids(conn, "open")  # Closed wins ties.
            confirm("open", "-10 minutes")
            confirm("closed", "1 hour")
            assert 2 in ids(conn, "open")  # Future closed ignored.
            confirm("open", "-1 minute", pharmacy=9)
            assert 9 not in ids(conn, "open")  # No active duty, despite open/future duty.
        finally:
            conn.rollback()
            conn.close()
        for mode in ("open", "24h"):
            self.run(sys.executable, "-B", "load/filters.py", mode, "--limit", "100")
        self.pass_check("multiple duties deduplicated; closed/open age, order, ties and future rules; both CLIs")

    def fail_fast(self):
        folder = self.temp / "bad-sql"
        folder.mkdir()
        (folder / "00_error.sql").write_text("SELECT 1;\nSELECT step0_missing_function();\n", encoding="utf-8")
        (folder / "01_must_not_run.sql").write_text("CREATE TABLE step0_must_not_exist(id int);\n", encoding="utf-8")
        override = self.temp / "failure.json"
        override.write_text(json.dumps({"services": {"seed": {"volumes": [
            {"type": "bind", "source": str(folder), "target": "/sql", "read_only": True}
        ]}}}), encoding="utf-8")
        before = self.snapshot()
        result = self.compose("--profile", "tools", "run", "--rm", "--no-deps", "seed",
                              override=override, check=False)
        assert result.returncode != 0, "SQL failure did not propagate"
        assert "01_must_not_run.sql" not in result.stdout
        assert self.conn.execute("SELECT to_regclass('step0_must_not_exist')").fetchone()[0] is None
        assert self.snapshot() == before
        self.pass_check("seed stops immediately with nonzero exit on SQL error; next SQL not executed")

    def osm_import(self):
        args = (sys.executable, "-B", "load/import_osm.py", "--file", "tests/fixtures/osm-small.json")
        first = self.run(*args).stdout
        second = self.run(*args).stdout
        assert "2 inserted, 0 updated" in first and "0 inserted, 2 updated" in second
        rows = self.conn.execute("SELECT osm_id FROM pharmacies WHERE osm_id LIKE '%/900000001' ORDER BY osm_id").fetchall()
        assert rows == [("node/900000001",), ("way/900000001",)]
        assert self.conn.execute("SELECT count(*) FROM pharmacies").fetchone()[0] == 22
        assert self.conn.execute("SELECT count(*) FROM v_open_now WHERE id IN (SELECT id FROM pharmacies WHERE osm_id IS NOT NULL)").fetchone()[0] == 0
        self.pass_check("local fake OSM import twice: types distinct, no duplicates, 24/7 tag grants no duty")

    def kafka_flow(self):
        logfile = self.temp / "consumer.log"
        with logfile.open("w", encoding="utf-8") as log:
            consumer = subprocess.Popen(
                [sys.executable, "-B", "load/consumer.py"], cwd=ROOT, env=self.env,
                stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                output = self.run(sys.executable, "-B", "load/simulator.py", "burst", "--count", "1", "--ids", "10").stdout
                assert "delivered" in output and "DELIVERY FAILED" not in output
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    assert consumer.poll() is None, logfile.read_text(encoding="utf-8")
                    count = self.conn.execute("SELECT count(*) FROM duty_rota WHERE pharmacy_id=10 AND source='simulator'").fetchone()[0]
                    if count:
                        break
                    time.sleep(0.5)
                else:
                    raise AssertionError("No consumed duty within 45 seconds\n" + logfile.read_text(encoding="utf-8"))
                assert count == 1
                assert self.conn.execute("SELECT count(*) FROM v_open_now WHERE id=10").fetchone()[0] == 1
            finally:
                consumer.terminate()
                try:
                    consumer.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    consumer.kill()
                    consumer.wait(timeout=10)
        assert "key=b'10'" in logfile.read_text(encoding="utf-8")
        self.pass_check("simulator CLI -> Kafka (key pharmacy_id) -> unchanged consumer -> database/view")

    def cleanup(self):
        if self.conn:
            self.conn.close()
        if self.claimed:
            self.assert_owned()
            # No prune, no orphan removal, no externally named volumes/networks.
            self.compose("--profile", "tools", "down", "--volumes", timeout=120)
            for kind, before in self.baseline.items():
                assert before <= self.resources()[kind], f"Pre-existing {kind} disappeared"
            for command in (("ps", "-aq"), ("volume", "ls", "-q"), ("network", "ls", "-q")):
                assert not self.run("docker", *command, "--filter",
                                    f"label=com.docker.compose.project={self.project}").stdout.strip()
            self.pass_check("only test-owned resources removed; pre-existing resources still present")

    def recreate_owned_services(self):
        self.assert_owned()
        before = self.snapshot()
        self.conn.close()
        self.conn = None
        self.compose("up", "-d", "--force-recreate", "--wait", "--wait-timeout", "180", "db", "kafka", timeout=240)
        self.assert_owned()
        import psycopg
        from confluent_kafka import Consumer
        self.conn = psycopg.connect(self.env["DATABASE_URL"], autocommit=True)
        assert self.snapshot() == before, "PostgreSQL data changed across container recreation"
        replay = Consumer({
            "bootstrap.servers": self.env["KAFKA_BOOTSTRAP"],
            "group.id": self.project + "-persistence", "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        })
        try:
            replay.subscribe(["duty-rota"])
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                message = replay.poll(1)
                if message is not None and not message.error():
                    assert message.key() == b"10"
                    assert json.loads(message.value())["pharmacy_id"] == 10
                    break
            else:
                raise AssertionError("Kafka message lost across container recreation")
        finally:
            replay.close()
        self.pass_check("recreating only test containers preserves PostgreSQL data and Kafka messages in named volumes")

    def execute(self):
        self.start()
        self.refuse_existing_project()
        self.seed()
        self.pass_check("full initialization from empty database, SQL 01-07 in order")
        self.seed()
        self.pass_check("full seed rerun succeeds with expected fixture counts")
        self.topics()
        self.legacy_upgrade()
        self.seed()  # Restore a fresh demo dataset after the legacy-only migration test.
        self.filter_rules()
        self.fail_fast()
        self.osm_import()
        self.kafka_flow()
        self.recreate_owned_services()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="pharmacy-step0-test-" + uuid.uuid4().hex[:12])
    args = parser.parse_args()
    try:
        checks = Step0Checks(args.project)
    except ValueError as exc:
        parser.error(str(exc))
    failed = False
    with tempfile.TemporaryDirectory(prefix="pharmacy-step0-test-") as temp:
        try:
            checks.prepare(temp)
            checks.execute()
        except Exception as exc:
            failed = True
            print(f"FAIL: {exc}", file=sys.stderr, flush=True)
            if checks.claimed:
                try:
                    print(checks.compose("logs", "--tail", "40", check=False).stdout, file=sys.stderr)
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
