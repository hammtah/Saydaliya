-- FAKE duty data so Slices B and C can work before Slice A delivers anything.
-- Times are relative to "now", so the demo is always "tonight" whenever you run the seed.
-- ids refer to the order of 02_seed.sql (1 = Al Amal, 3 = Atlas, 4 = Bourgogne, ...).

INSERT INTO duty_rota (pharmacy_id, starts_at, ends_at, source)
SELECT id, now() - interval '2 hours', now() + interval '10 hours', 'seed'
FROM pharmacies
WHERE id IN (1, 3, 4, 6, 8, 11, 13, 16);

-- Pharmacy 1 was confirmed open 12 minutes ago.
-- Pharmacy 4 was reported closed 10 minutes ago, even though the rota says on duty.
INSERT INTO confirmations (event_id, pharmacy_id, status, confirmed_at) VALUES
    (gen_random_uuid(), 1, 'open',   now() - interval '12 minutes'),
    (gen_random_uuid(), 4, 'closed', now() - interval '10 minutes');
