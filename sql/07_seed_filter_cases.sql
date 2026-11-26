-- Three distinct FAKE fixtures, absent from the duty/confirmation seed in 04.
-- Rebuilt by the full seed; relative timestamps are fixed within this transaction.
BEGIN;

INSERT INTO duty_rota (pharmacy_id, starts_at, ends_at, source) VALUES
    (2, now() - interval '2 hours',  now() + interval '22 hours', 'seed'),
    (5, now() - interval '2 hours',  now() + interval '10 hours', 'seed'),
    (9, now() - interval '26 hours', now() - interval '2 hours',  'seed');

-- 2: exactly 24 hours, active -> Open now AND 24h.
-- 5: exactly 12 hours, active -> Open now only.
-- 9: exactly 24 hours, expired -> neither filter.
COMMIT;
