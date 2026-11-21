# load/ (Slice A: who is on duty tonight?)

Scripts that fill the database with pharmacies and duty rotas. Run every command from the **repo root**.

## One-time setup

| Command | What it does |
|---|---|
| `pip install -r requirements.txt` | Installs the Python libraries (`confluent-kafka` for Kafka, `psycopg` for PostgreSQL). |
| `docker compose up -d` | Starts PostgreSQL/PostGIS and Kafka in the background. |
| `docker compose --profile tools run --build --rm seed` | Runs every file in `sql/` in order: tables, 20 fake pharmacies, fake duty data, the `v_open_now` view. **It wipes and recreates the tables**, so anything imported before is lost (run the OSM import again afterwards). |
| `python load/import_osm.py` | Downloads the real pharmacies of Casablanca from OpenStreetMap and saves them in the database. Safe to run twice: existing pharmacies are updated, not duplicated. |
| `docker exec pharmacy-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic duty-rota --partitions 3` | Creates the `duty-rota` Kafka topic (the mailbox for duty messages). |

Options for the import: `--dry-run` (report only, change nothing), `--save-raw osm.json` (keep the download), `--file osm.json` (reuse a saved download, no network).

## Running the app

Use two terminals.

| Terminal | Command | What it does |
|---|---|---|
| 1 | `python load/consumer.py` | Listens to `duty-rota`, checks each message, and saves the duty window in the database. Bad messages are logged and skipped. Stop with Ctrl+C. |
| 2 | `python load/simulator.py burst --count 8` | Sends 8 fake duty messages (random pharmacies, on duty now) and exits. |
| 2 | `python load/simulator.py live` | Keeps switching random pharmacies on and off every 3 seconds, until Ctrl+C. |
| 2 | `python load/simulator.py live --interval 1 --bad-rate 0.2` | Same, but faster and with 20% garbage messages, to see the consumer survive them. |

## Checking the result

| Command | What it does |
|---|---|
| `python load/filters.py open` | The 10 nearest pharmacies that are open now (everything in `v_open_now`). |
| `python load/filters.py 24h` | Same, but only the 24h pharmacies. |
| `python load/filters.py open --lat 33.59 --lon -7.63 --limit 5` | Nearest from a given position (default: centre of Casablanca). |
| `python load/filters.py open --explain` | Shows how PostgreSQL runs the query (`EXPLAIN ANALYZE`). |
| `docker exec pharmacy-db psql -U pharma -d pharmacy -c "SELECT id, name FROM v_open_now ORDER BY id"` | Lists the pharmacies open now, straight from the database. |

## One-minute demo

1. `python load/consumer.py` (terminal 1)
2. `python load/simulator.py burst --count 5` (terminal 2)
3. `python load/filters.py open`: the 5 pharmacies are now in the list.

## Useful to know

- **Settings** are environment variables, all with defaults for the Docker setup: `DATABASE_URL` (default `postgresql://pharma:pharma@localhost:5432/pharmacy`), `KAFKA_BOOTSTRAP` (default `localhost:9092`), `GROUP_ID` (consumer group, default `duty-rota-consumer`).
- **Clear simulated duty data:** `docker exec pharmacy-db psql -U pharma -d pharmacy -c "DELETE FROM duty_rota WHERE source = 'simulator'"`
- **Reset everything:** `docker compose down -v`, then start again from `docker compose up -d`.
- The message formats are in `docs/data-contract.md`. Do not change them without telling the team.