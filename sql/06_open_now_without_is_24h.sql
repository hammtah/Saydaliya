-- Shared Step 0 change: a 24h duty is a CURRENT window lasting exactly 24 hours.
-- Keep 01..05 unchanged. This migration also upgrades populated legacy databases.
BEGIN;

-- Drop only this view, never its dependants. Unexpected dependencies fail safely.
DROP VIEW IF EXISTS v_open_now;

CREATE VIEW v_open_now AS
SELECT
    p.id,
    p.name,
    p.address,
    p.phone,
    p.geom,
    lc.status AS last_status,
    lc.confirmed_at AS last_confirmed_at,
    EXISTS (
        SELECT 1
        FROM duty_rota d
        WHERE d.pharmacy_id = p.id
          AND d.starts_at <= now()
          AND now() < d.ends_at
          AND d.ends_at - d.starts_at = interval '24 hours'
    ) AS has_active_24h_duty
FROM pharmacies p
LEFT JOIN LATERAL (
    SELECT c.status, c.confirmed_at
    FROM confirmations c
    WHERE c.pharmacy_id = p.id
      AND c.confirmed_at > now() - interval '60 minutes'
      AND c.confirmed_at <= now()
    -- Only a STRICTLY newer open cancels closed; closed wins timestamp ties.
    ORDER BY c.confirmed_at DESC, (c.status = 'closed') DESC, c.id DESC
    LIMIT 1
) lc ON TRUE
WHERE EXISTS (
    SELECT 1
    FROM duty_rota d
    WHERE d.pharmacy_id = p.id
      AND d.starts_at <= now()
      AND now() < d.ends_at
)
AND COALESCE(lc.status, 'open') <> 'closed';

-- The replacement view no longer depends on this column. No CASCADE is needed.
ALTER TABLE pharmacies DROP COLUMN IF EXISTS is_24h;

COMMIT;
