# Night Pharmacy Finder — shared Step 0

PostgreSQL/PostGIS, Kafka, reproducible fake data and the Slice A command-line
scripts. There is no API or user interface yet. Run commands from the repository
root. Examples use **PowerShell**; Docker and Python commands also work in other
shells. Requires Docker Engine/Desktop, Docker Compose v2.20+ and Python 3.10+.

## Fresh clone: first setup

Use this section only for a new development database. For an existing installation,
read **Existing installation** first.

```powershell
python -m pip install -r requirements.txt
docker compose up -d --wait --wait-timeout 180 db kafka
docker compose exec -T db sh -ec 'until pg_isready -h 127.0.0.1 -U pharma -d pharmacy; do sleep 1; done'
docker compose run --rm kafka-init
docker compose --profile tools run --rm seed
```

- `up --wait` waits for PostGIS and Kafka healthchecks. The additional TCP check
  avoids accepting PostgreSQL's temporary Unix-socket server during first-time
  PostGIS initialization: it can stop/restart after a socket healthcheck succeeds.
- `kafka-init` waits for Kafka and creates **duty-rota** and **confirmations**, each
  with **3 partitions, replication factor 1**. It also starts automatically with
  a plain `docker compose up -d`. Re-running it is safe: `--if-not-exists` keeps
  existing topics. It does not repair existing topics with wrong partition counts;
  inspect them and coordinate any correction with the team.
- `seed` waits for PostGIS and executes **all `sql/*.sql` in filename order**,
  including 06 and 07. A SQL error immediately returns a nonzero exit code and stops
  subsequent files. Earlier files may have committed: the full seed is not atomic.
- Only direct `*.sql` files under `sql/` are executed: **no files from `demo/`,
  `tests/`, `.local-backups/` or other directories**, and no recursive subdirectories.
- **WARNING: `seed` erases existing database data.** Historical files 01 and 03
  drop/recreate tables. Re-running it resets imported pharmacies, duty periods and
  confirmations. Never use it to upgrade data you want to keep.

To resume an already initialized installation **whose containers and storage have
already been migrated to the current Compose configuration**:

```powershell
docker compose up -d --wait --wait-timeout 180 db kafka
docker compose exec -T db sh -ec 'until pg_isready -h 127.0.0.1 -U pharma -d pharmacy; do sleep 1; done'
docker compose run --rm kafka-init
```

Do not repeat `seed` unless resetting that development database is intended.
For legacy containers, follow **Existing installation** instead; running `up`
before preparing the Kafka storage migration can lose access to old broker data.

## Settings and changed ports

Default host ports remain **PostGIS 5432** and **Kafka 9092**.

| Variable | Used by | Default |
|---|---|---|
| `POSTGRES_PORT` | Compose host port | `5432` |
| `KAFKA_PORT` | Compose host port **and advertised HOST listener** | `9092` |
| `DATABASE_URL` | Python scripts | `postgresql://pharma:pharma@localhost:5432/pharmacy` |
| `KAFKA_BOOTSTRAP` | Python producer/consumer | `localhost:9092` |
| `GROUP_ID` | Duty consumer | `duty-rota-consumer` |

For example, set these in **each terminal** before setup or Python commands:

```powershell
$env:POSTGRES_PORT = "15432"
$env:KAFKA_PORT = "19092"
$env:DATABASE_URL = "postgresql://pharma:pharma@localhost:15432/pharmacy"
$env:KAFKA_BOOTSTRAP = "localhost:19092"
```

Compose port variables do not automatically update Python's connection variables.
Kafka advertises `localhost:${KAFKA_PORT}` to host clients and `kafka:29092` to
containers. This setup targets clients on the same computer.

## Check the shared setup

```powershell
docker compose ps -a
docker compose exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:29092 --describe --topic duty-rota
docker compose exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:29092 --describe --topic confirmations
docker compose exec -T db psql -U pharma -d pharmacy -c "SELECT id, name, has_active_24h_duty FROM v_open_now ORDER BY id"
python load/filters.py open --limit 20
python load/filters.py 24h --limit 20
```

File 07 adds independent fixtures with timestamps relative to seed execution:

| ID | Pharmacy | Duty | Expected filters |
|---|---|---|---|
| 2 | Ibn Sina | Active, exactly 24 hours (`now()-2h` to `now()+22h`) | Open now and 24h |
| 5 | Racine | Active, exactly 12 hours (`now()-2h` to `now()+10h`) | Open now only |
| 9 | Habous | Expired 24-hour period (`now()-26h` to `now()-2h`) | Neither |

These IDs have no duty periods or confirmations from file 04. Other seeded
pharmacies can also appear in Open now. Relative dates do expire; results are
expected immediately after initialization, not indefinitely.

**Open now** includes any active duty unless a recent closed confirmation excludes
it. **24h** is the subset where the view's `has_active_24h_duty` is true, not a
permanent OSM property. Night is postponed; All needs a team definition. See the
[data contract](docs/data-contract.md) for exact confirmation rules.

## One-minute Kafka demo

Complete setup and readiness first. In terminal 1:

```powershell
python load/consumer.py
```

In terminal 2, with the same connection variables:

```powershell
python load/simulator.py burst --count 1 --ids 10
python load/filters.py open --limit 20
```

Pharmacy 10 has no initial duty or confirmation: after consumption it should
appear in Open now. Delivery and consumption are asynchronous; check the consumer
log before searching. These are fake data, not proof of a real-world opening.

Optional: `python load/simulator.py live`. Closing a simulator-created period does
not cancel another active period for the same pharmacy.

The duty consumer is unchanged in this Step 0 work. Known defects remain: a list
or object in `source` can raise an uncaught `TypeError`; an out-of-range integer
ID can raise an uncaught database error. Its bad-message handling does not guarantee
survival of every malformed message. No confirmations consumer exists yet.

## 24h SQL demo without resetting an existing database

This demo requires the schema after migration 06. It does not use Kafka, run the
full seed, apply file 07, recreate containers or reset existing data. Stop/avoid
simulator producers during it so they cannot add extra duties to the fake records.

First check that these reserved IDs are unused. If this returns any row, inspect
it before proceeding; never delete or overwrite it blindly:

```powershell
docker compose exec -T db psql -U pharma -d pharmacy -X -c "SELECT id, name, address FROM pharmacies WHERE id IN (-24001,-24002,-24003)"
```

The [add script](demo/add_24h.sql) creates three new pharmacies, each with exactly
one duty and no confirmation. Their address marker is `DEMO24H-20261126`, their
names start with `DEMO24H:`, and `osm_id` is NULL. They are fictitious locations.

| ID | Name | Duty relative to transaction time | Open now | 24h |
|---|---|---|---|---|
| -24001 | DEMO24H: active 24h | `now()-1h` to `now()+23h` | Once | Once |
| -24002 | DEMO24H: active 12h | `now()-1h` to `now()+11h` | Once | Absent |
| -24003 | DEMO24H: expiree | `now()-26h` to `now()-2h` | Absent | Absent |

Execute only after approving the addition to the intended database. The example
connection targets the default local port; adjust it if using a different port:

```powershell
$env:DATABASE_URL = "postgresql://pharma:pharma@localhost:5432/pharmacy"
Get-Content -Raw demo/add_24h.sql | docker compose exec -T db psql -U pharma -d pharmacy -X -v ON_ERROR_STOP=1
if ($LASTEXITCODE -ne 0) { throw "Demo add failed; inspect the error before continuing." }

$count = docker compose exec -T db psql -U pharma -d pharmacy -Atc "SELECT count(*) FROM pharmacies"
if ($LASTEXITCODE -ne 0) { throw "Could not determine the result limit." }
$limit = [int]$count
python load/filters.py open --limit $limit
python load/filters.py 24h --limit $limit
```

The limit covers every pharmacy in the database, so nearby existing pharmacies
cannot hide the demo cases. Other results depend on their own duty windows and
confirmations; their total is not fixed. Run the demo before its active windows end.

A second add is **intentionally refused** by the primary key (psql exit code 3).
The transaction rolls back without duplicate rows or refreshed times. Do not add
`ON CONFLICT DO NOTHING`: that could silently reuse unrelated records at those IDs.

To remove the demo, use only the [guarded removal script](demo/remove_24h.sql):

```powershell
Get-Content -Raw demo/remove_24h.sql | docker compose exec -T db psql -U pharma -d pharmacy -X -v ON_ERROR_STOP=1
if ($LASTEXITCODE -ne 0) { throw "Demo removal refused; inspect the records without deleting them." }
docker compose exec -T db psql -U pharma -d pharmacy -X -c "SELECT id, name, address FROM pharmacies WHERE id IN (-24001,-24002,-24003) OR name LIKE 'DEMO24H:%' OR address LIKE 'DEMO24H%'"
```

Removal verifies ownership markers, one duty with the expected source/duration,
and absence of confirmations before deleting. A confirmation, additional duty or
unexpected modification makes it refuse the entire removal without deleting rows.
The schema's `ON DELETE CASCADE` removes the duties belonging to these three
pharmacies only. A second removal succeeds without effect. Successful insertions
advance duty sequences normally; removal never resets sequences. After removal,
the add script can be used again with new relative times.

Validate the scripts separately, on a new isolated PostGIS test project:

```powershell
python -B tests/test_demo_24h.py
```

This runner never connects to the developer database and starts no Kafka broker.
It checks the two filters, duplicate-add refusal, repeated removal, preservation
of other rows and refusal after a confirmation. It cleans only its own resources.

## Optional OSM import

After setup, without network access:

```powershell
python load/import_osm.py --file tests/fixtures/osm-small.json --dry-run
python load/import_osm.py --file tests/fixtures/osm-small.json
```

The fixture is entirely fake. For real pharmacy locations, use
`python load/import_osm.py`. Options: `--save-raw osm.json` and `--file osm.json`.
Imports update objects by unique `osm_id` (including node/way/relation type), keep
the initial fake pharmacies and never create duty periods from OSM's 24/7 tag.

## Existing installation: preserve data

Announce schema changes to the team before applying them. Files 01–05 are
unchanged; **06 alone upgrades their schema without clearing table data**. File
07 supplies demo data and is not needed for this upgrade.

### Apply 06 without recreating containers or running seed

Use the **same Compose project name and directory as the existing installation**.
For the original folder this is normally `pharmacy-garden`. Inspect it first:

```powershell
docker compose ps -a
docker compose exec -T db pg_isready -h 127.0.0.1 -U pharma -d pharmacy
```

After an appropriate backup, apply 06 directly to the running database. This
PowerShell command also waits for PostgreSQL readiness:

```powershell
Get-Content -Raw sql/06_open_now_without_is_24h.sql | docker compose exec -T db sh -ec 'until pg_isready -h 127.0.0.1 -U pharma -d pharmacy; do sleep 1; done; exec psql -U pharma -d pharmacy -X -v ON_ERROR_STOP=1'
```

In Bash, replace `Get-Content -Raw` with `cat`. Check the shell exit code, then:

```powershell
docker compose exec -T db psql -U pharma -d pharmacy -c "SELECT id, name, has_active_24h_duty FROM v_open_now ORDER BY id"
```

Migration 06 replaces only `v_open_now` and removes `pharmacies.is_24h`, inside a
transaction, without `CASCADE`. Other table values and sequences are preserved.
The removed boolean values are intentionally discarded; back them up if needed.
Unexpected dependent views make it fail and roll back rather than disappear.
The updated Python scripts require this migration.
This command does not start/recreate services, run `seed` or change Kafka storage.
Check the exit code and stop if it fails. Back up PostgreSQL and verify the backup
is restorable first; keep the same project, database, role and existing volume.

### What changing Compose does

- Removing `container_name` lets Compose generate project-scoped names. On a future
  `up`, changed services may be recreated. Commands now target services with
  `docker compose exec db ...` or `docker compose exec kafka ...`.
- Keeping the same project preserves the `pgdata` volume identity, normally
  `pharmacy-garden_pgdata`. Another directory/project creates a different volume:
  old data is not deleted, but the new database will look empty.
- This version introduces project-scoped **`kafka_data`**, with logs explicitly in
  `/var/lib/kafka/data`. **It does not migrate old broker logs, topics, messages or
  committed offsets automatically.** The original image may have used an anonymous
  volume or the container filesystem. Inspect its log directory and mounts and
  arrange backup/migration before recreating it if those data matter. An empty new
  volume means an empty broker; topic initialization cannot recover messages.
  Do not run `up` against a legacy broker until its storage/metadata backup and
  migration plan have been agreed. Applying database migration 06 alone does not
  require changing that broker. The automated tests prove persistence for the new
  named-volume setup, not recovery of a particular legacy Kafka installation.
- There is no fixed network/volume `name:` or `external:` resource. Each project
  gets its own default network and named volumes. Host ports can still conflict;
  select free alternatives before starting a second project.
- `docker compose stop` keeps volumes. Avoid `down -v`, volume pruning and full
  seed on any installation whose data must be kept.

The existing installation was only inspected during development, not recreated or
reset. Preservation tests use the legacy schema with fake data in an isolated
project, not teammates' databases.

## Reproducible isolated integration checks

```powershell
python -B tests/test_step0.py
```

Requires Docker access and the Python dependencies. The runner generates a new
`pharmacy-step0-test-<12 hex digits>` project, chooses free ports and overrides
both Python connection variables. It ignores repository `.env` and inherited
Compose project/file settings. It refuses ordinary project names, already-used
test namespaces, fixed container names, shared volumes/networks and writable
source mounts. Example of intentional refusal, before any Docker/database call:

```powershell
python -B tests/test_step0.py --project pharmacy-garden
```

Checks cover empty initialization; repeated seed and topic creation; topic
partitions and replication; populated legacy upgrade preserving rows and sequences;
filter cases and overlapping duties; closed/open timing; SQL failure propagation;
local fake OSM import twice; and simulator → Kafka → consumer → database.
They also verify refusal to reuse an active test project and preservation of
database rows and Kafka messages when only test containers are recreated.

Tests reset only their fresh database. Cleanup targets only their verified project
and volumes, never global pruning or another project. Existing resource identifiers
are checked to remain present. A failed test returns nonzero and prints logs;
cleanup failures identify the project whose resources may remain.

## Files to keep local

The bundled `pharma` / `pharma` credentials are development defaults, not production
secrets. Keep real passwords, tokens, `.env` files and database dumps out of Git.
Also exclude `.local-backups/`, the local `ANALYSE_PROJET.md` report and generated
Python `__pycache__/` / `*.pyc` files. They are not all covered by the current
`.gitignore`; stage an explicit reviewed file list rather than `git add .`.

Configuration references: [Apache Kafka 3.8 example](https://github.com/apache/kafka/blob/3.8.0/docker/examples/docker-compose-files/single-node/plaintext/docker-compose.yml),
[Compose readiness](https://docs.docker.com/compose/how-tos/startup-order/) and
[Compose volumes](https://docs.docker.com/reference/compose-file/volumes/).
