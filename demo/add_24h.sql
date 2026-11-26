-- FAKE demo only. Fixed negative IDs are reserved for these three records.
-- Run with psql -v ON_ERROR_STOP=1. A repeated add intentionally fails atomically.
BEGIN;

INSERT INTO pharmacies (id, name, address, geom) VALUES
(
    -24001, 'DEMO24H: active 24h', 'DEMO24H-20261126',
    ST_SetSRID(ST_MakePoint(-7.6200, 33.5900), 4326)::geography
),
(
    -24002, 'DEMO24H: active 12h', 'DEMO24H-20261126',
    ST_SetSRID(ST_MakePoint(-7.6201, 33.5900), 4326)::geography
),
(
    -24003, 'DEMO24H: expiree', 'DEMO24H-20261126',
    ST_SetSRID(ST_MakePoint(-7.6202, 33.5900), 4326)::geography
);

INSERT INTO duty_rota (pharmacy_id, starts_at, ends_at, source) VALUES
    (-24001, now() - interval '1 hour',
              now() + interval '23 hours', 'manual'),
    (-24002, now() - interval '1 hour',
              now() + interval '11 hours', 'manual'),
    (-24003, now() - interval '26 hours',
              now() - interval '2 hours', 'manual');

COMMIT;
