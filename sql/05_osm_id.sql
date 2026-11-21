-- Slice A, feature 1: remember which OpenStreetMap object a pharmacy came from.
-- Without this, running the OSM import twice would insert every pharmacy twice.
--
-- osm_id looks like 'node/123456' or 'way/987654'. We store the type too because
-- OSM numbers are only unique *within* a type (node 5 and way 5 are different things).
-- The 20 fake pharmacies keep osm_id = NULL. UNIQUE allows many NULLs in PostgreSQL.

ALTER TABLE pharmacies ADD COLUMN IF NOT EXISTS osm_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS pharmacies_osm_id_key ON pharmacies (osm_id);
