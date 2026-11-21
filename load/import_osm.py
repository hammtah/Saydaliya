"""Slice A, feature 1: load the real pharmacies of Casablanca from OpenStreetMap.

Usage:
    pip install "psycopg[binary]"
k    python load/import_osm.py                 # download from Overpass, then import
    python load/import_osm.py --dry-run       # download and show what WOULD be imported
    python load/import_osm.py --file osm.json # reuse a saved download (no network)

Running it twice is safe: rows are matched on osm_id and updated, not duplicated.
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

# --- Configuration -----------------------------------------------------------

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://pharma:pharma@localhost:5432/pharmacy"
)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Bounding box around Casablanca: (south, west, north, east).
# Simple and robust. A more precise alternative is to ask Overpass for the city's
# administrative area, but that needs the right boundary relation to be found first.
BBOX = (33.45, -7.75, 33.68, -7.45)

# Overpass QL, the query language of Overpass.
#   nwr = node + way + relation (a pharmacy can be a point OR a building outline)
#   out center tags = give every object a single point ("center") plus its tags
OVERPASS_QUERY = """
[out:json][timeout:60];
nwr["amenity"="pharmacy"]({s},{w},{n},{e});
out center tags;
""".format(s=BBOX[0], w=BBOX[1], n=BBOX[2], e=BBOX[3])

# Fallbacks, because our table has name and address as NOT NULL but OSM is incomplete.
DEFAULT_NAME = "Pharmacie (sans nom)"
DEFAULT_ADDRESS = "Casablanca"


# --- Step 1: download --------------------------------------------------------

def download():
    """Send the query to Overpass and return the parsed JSON."""
    data = urllib.parse.urlencode({"data": OVERPASS_QUERY}).encode()
    request = urllib.request.Request(
        OVERPASS_URL,
        data=data,  # giving data makes this a POST
        headers={"User-Agent": "night-pharmacy-finder-student-project/0.1"},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)


# --- Step 2: turn OSM elements into rows -------------------------------------

def build_address(tags):
    """Build a readable address from OSM address tags, or fall back."""
    street = tags.get("addr:street")
    number = tags.get("addr:housenumber")
    area = tags.get("addr:suburb") or tags.get("addr:neighbourhood")
    city = tags.get("addr:city")

    street_part = " ".join(p for p in (number, street) if p)
    parts = [p for p in (street_part, area, city) if p]
    return ", ".join(parts) if parts else DEFAULT_ADDRESS


def parse_element(element):
    """Convert one OSM element to a dict ready for the database.

    Returns None if the element has no usable position.
    """
    tags = element.get("tags", {})

    # Nodes carry lat/lon directly. Ways and relations carry a computed "center".
    if element["type"] == "node":
        lat, lon = element.get("lat"), element.get("lon")
    else:
        center = element.get("center", {})
        lat, lon = center.get("lat"), center.get("lon")

    if lat is None or lon is None:
        return None

    return {
        "osm_id": f"{element['type']}/{element['id']}",
        "name": tags.get("name") or tags.get("name:fr") or DEFAULT_NAME,
        "address": build_address(tags),
        "phone": tags.get("phone") or tags.get("contact:phone"),
        "is_24h": tags.get("opening_hours") == "24/7",
        "lat": lat,
        "lon": lon,
    }


def parse_all(payload):
    rows, skipped = [], 0
    for element in payload.get("elements", []):
        row = parse_element(element)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    return rows, skipped


# --- Step 3: write to the database -------------------------------------------

# ST_MakePoint takes (LONGITUDE, latitude): x first, then y. Easy to get backwards!
# ON CONFLICT (osm_id) DO UPDATE is the "upsert": insert, or update if it exists.
# (xmax = 0) is a PostgreSQL trick: true for a fresh insert, false for an update.
UPSERT_SQL = """
INSERT INTO pharmacies (osm_id, name, address, phone, is_24h, geom)
VALUES (
    %(osm_id)s, %(name)s, %(address)s, %(phone)s, %(is_24h)s,
    ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography
)
ON CONFLICT (osm_id) DO UPDATE SET
    name    = EXCLUDED.name,
    address = EXCLUDED.address,
    phone   = EXCLUDED.phone,
    is_24h  = EXCLUDED.is_24h,
    geom    = EXCLUDED.geom
RETURNING (xmax = 0) AS inserted;
"""


def save(rows):
    import psycopg  # imported here so --dry-run works without it installed

    inserted = updated = 0
    # "with connect" wraps everything in ONE transaction: all rows or none.
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(UPSERT_SQL, row)
                if cur.fetchone()[0]:
                    inserted += 1
                else:
                    updated += 1
    return inserted, updated


# --- Main --------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--file", help="read this saved Overpass JSON instead of downloading")
    parser.add_argument("--save-raw", metavar="PATH", help="also save the raw download to this file")
    parser.add_argument("--dry-run", action="store_true", help="parse and report, do not touch the database")
    args = parser.parse_args()

    if args.file:
        with open(args.file, encoding="utf-8") as f:
            payload = json.load(f)
    else:
        print("Downloading from Overpass...")
        payload = download()
        if args.save_raw:
            with open(args.save_raw, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)

    rows, skipped = parse_all(payload)

    no_name = sum(r["name"] == DEFAULT_NAME for r in rows)
    no_phone = sum(r["phone"] is None for r in rows)
    no_address = sum(r["address"] == DEFAULT_ADDRESS for r in rows)
    n_24h = sum(r["is_24h"] for r in rows)

    print(f"OSM elements parsed : {len(rows)} (skipped without position: {skipped})")
    print(f"  without a name    : {no_name}")
    print(f"  without a phone   : {no_phone}")
    print(f"  without an address: {no_address}")
    print(f"  tagged 24/7       : {n_24h}")

    if args.dry_run:
        print("Dry run: database not touched.")
        return

    inserted, updated = save(rows)
    print(f"Database: {inserted} inserted, {updated} updated.")


if __name__ == "__main__":
    sys.exit(main())
