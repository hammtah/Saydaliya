-- Milestone 2: minimal shared schema.
-- Duty rota and confirmation tables come later (agreed in Milestone 3, built in the slices).

CREATE EXTENSION IF NOT EXISTS postgis;

DROP TABLE IF EXISTS pharmacies CASCADE;

CREATE TABLE pharmacies (
    id        SERIAL PRIMARY KEY,
    name      TEXT NOT NULL,
    address   TEXT NOT NULL,
    phone     TEXT,
    is_24h    BOOLEAN NOT NULL DEFAULT FALSE,
    geom      GEOGRAPHY(Point, 4326) NOT NULL
);

-- Spatial index: this is what makes "nearest pharmacy" fast (used in the Speed test, feature 10)
CREATE INDEX pharmacies_geom_idx ON pharmacies USING GIST (geom);
