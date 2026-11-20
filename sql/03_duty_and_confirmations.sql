-- Milestone 3: tables fed by Kafka + the shared "open now" view.
-- See docs/data-contract.md for the message formats and the rules.

DROP VIEW  IF EXISTS v_open_now;
DROP TABLE IF EXISTS duty_rota, confirmations CASCADE;

-- Topic "duty-rota": a pharmacy is on duty between starts_at and ends_at.
CREATE TABLE duty_rota (
    id           BIGSERIAL PRIMARY KEY,
    pharmacy_id  INT NOT NULL REFERENCES pharmacies(id) ON DELETE CASCADE,
    starts_at    TIMESTAMPTZ NOT NULL,
    ends_at      TIMESTAMPTZ NOT NULL,
    source       TEXT NOT NULL DEFAULT 'unknown',   -- simulator | manual | scraper | seed
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (ends_at > starts_at),
    -- Kafka can deliver a message twice: the consumer uses
    -- INSERT ... ON CONFLICT (pharmacy_id, starts_at) DO UPDATE SET ends_at = EXCLUDED.ends_at
    UNIQUE (pharmacy_id, starts_at)
);

-- Topic "confirmations": a user says the pharmacy is open or closed.
CREATE TABLE confirmations (
    id            BIGSERIAL PRIMARY KEY,
    event_id      UUID NOT NULL UNIQUE,             -- makes replays harmless (ON CONFLICT DO NOTHING)
    pharmacy_id   INT NOT NULL REFERENCES pharmacies(id) ON DELETE CASCADE,
    status        TEXT NOT NULL CHECK (status IN ('open', 'closed')),
    confirmed_at  TIMESTAMPTZ NOT NULL,
    received_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX confirmations_pharmacy_time_idx ON confirmations (pharmacy_id, confirmed_at DESC);

-- The single definition of "open right now". Everyone queries this view,
-- so the nearest search, the filters and the coverage map always agree.
--   open now = (24h pharmacy OR inside a duty window)
--              AND NOT reported closed in the last 60 minutes
CREATE VIEW v_open_now AS
SELECT
    p.id,
    p.name,
    p.address,
    p.phone,
    p.is_24h,
    p.geom,
    lc.status       AS last_status,        -- latest confirmation in the last 60 min (or NULL)
    lc.confirmed_at AS last_confirmed_at   -- for the "Confirmed 12 min ago" label
FROM pharmacies p
LEFT JOIN LATERAL (
    SELECT c.status, c.confirmed_at
    FROM confirmations c
    WHERE c.pharmacy_id = p.id
      AND c.confirmed_at > now() - interval '60 minutes'
    ORDER BY c.confirmed_at DESC
    LIMIT 1
) lc ON TRUE
WHERE (
        p.is_24h
        OR EXISTS (
            SELECT 1 FROM duty_rota d
            WHERE d.pharmacy_id = p.id
              AND now() >= d.starts_at
              AND now() <  d.ends_at
        )
      )
  AND COALESCE(lc.status, 'open') <> 'closed';
