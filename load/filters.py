"""Slice A, feature 3: Open now / 24h queries (command line, no UI yet).

Usage:
    pip install "psycopg[binary]"
    python load/filters.py open
    python load/filters.py 24h
    python load/filters.py open --lat 33.59 --lon -7.63 --limit 5
    python load/filters.py open --explain      # show how PostgreSQL runs the query

Everything goes through the view v_open_now (data contract: nobody rewrites "open now").
The two filters only differ by one WHERE line:

    open   -> no filter                 (everything open right now)
    24h    -> WHERE has_active_24h_duty  (an active duty lasting exactly 24 hours)

A "Night" filter is postponed: see the discussion about what a duty window means.
The meaning of "All" still needs a team decision.
"""

import argparse
import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://pharma:pharma@localhost:5432/pharmacy"
)

# Default position: roughly the centre of Casablanca (longitude, latitude).
DEFAULT_LON, DEFAULT_LAT = -7.6200, 33.5900

# Fixed SQL fragments, chosen by name. Nothing the user types is pasted into the SQL:
# position and limit go through %(...)s parameters, which is how you avoid SQL injection.
FILTERS = {
    "open": "",
    "24h": "WHERE has_active_24h_duty",
}

QUERY = """
SELECT
    id, name, address, has_active_24h_duty, last_status, last_confirmed_at,
    ST_Distance(geom, here.pt) AS distance_m
FROM v_open_now,
     (SELECT ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography AS pt) AS here
{where}
ORDER BY geom <-> here.pt          -- "<->" = distance operator, can use the GIST index
LIMIT %(limit)s
"""


def build_query(filter_name):
    return QUERY.format(where=FILTERS[filter_name])


def main():
    import psycopg

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("filter", choices=FILTERS)
    parser.add_argument("--lat", type=float, default=DEFAULT_LAT)
    parser.add_argument("--lon", type=float, default=DEFAULT_LON)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--explain", action="store_true", help="run EXPLAIN ANALYZE instead")
    args = parser.parse_args()

    sql = build_query(args.filter)
    params = {"lat": args.lat, "lon": args.lon, "limit": args.limit}

    with psycopg.connect(DATABASE_URL) as conn:
        if args.explain:
            for (line,) in conn.execute("EXPLAIN ANALYZE " + sql, params):
                print(line)
            return

        rows = conn.execute(sql, params).fetchall()

    print(f"filter={args.filter}: {len(rows)} pharmacies (nearest first)")
    for id_, name, address, has_24h_duty, status, confirmed_at, dist in rows:
        tags = ("24h " if has_24h_duty else "duty") + (f" last={status}" if status else "")
        print(f"  {id_:>4}  {dist / 1000:5.2f} km  [{tags:<14}] {name} - {address}")


if __name__ == "__main__":
    main()
