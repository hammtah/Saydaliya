-- Remove only the three identified demo pharmacies and their one duty each.
-- Refuse unexpected changes/reports instead of silently deleting them.
BEGIN;

DO $$
BEGIN
    PERFORM id FROM pharmacies
    WHERE id IN (-24001, -24002, -24003)
    FOR UPDATE;

    IF EXISTS (
        SELECT 1
        FROM pharmacies p
        WHERE p.id IN (-24001, -24002, -24003)
          AND (
              p.address <> 'DEMO24H-20261126'
              OR p.name <> CASE p.id
                  WHEN -24001 THEN 'DEMO24H: active 24h'
                  WHEN -24002 THEN 'DEMO24H: active 12h'
                  WHEN -24003 THEN 'DEMO24H: expiree'
              END
              OR p.osm_id IS NOT NULL
              OR (SELECT count(*) FROM duty_rota d
                  WHERE d.pharmacy_id = p.id) <> 1
              OR EXISTS (
                  SELECT 1 FROM confirmations c
                  WHERE c.pharmacy_id = p.id
              )
              OR EXISTS (
                  SELECT 1 FROM duty_rota d
                  WHERE d.pharmacy_id = p.id
                    AND (
                        d.source <> 'manual'
                        OR d.ends_at - d.starts_at <>
                            CASE WHEN p.id = -24002
                                THEN interval '12 hours'
                                ELSE interval '24 hours'
                            END
                    )
              )
          )
    ) THEN
        RAISE EXCEPTION
            'Donnees de demo modifiees : retrait refuse';
    END IF;

    DELETE FROM pharmacies
    WHERE id IN (-24001, -24002, -24003)
      AND address = 'DEMO24H-20261126';
END $$;

COMMIT;
