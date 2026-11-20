-- 20 FAKE pharmacies spread across Casablanca. Names, phones and exact positions are invented.
-- ST_MakePoint takes (longitude, latitude), in that order.

INSERT INTO pharmacies (name, address, phone, is_24h, geom) VALUES
('Pharmacie Al Amal',        'Rue d''Alger, Maarif',          '+212522000001', FALSE, ST_SetSRID(ST_MakePoint(-7.6350, 33.5890), 4326)::geography),
('Pharmacie Ibn Sina',       'Bd Zerktouni, Maarif',          '+212522000002', TRUE,  ST_SetSRID(ST_MakePoint(-7.6300, 33.5860), 4326)::geography),
('Pharmacie Atlas',          'Rue Gauthier, Gauthier',        '+212522000003', FALSE, ST_SetSRID(ST_MakePoint(-7.6280, 33.5900), 4326)::geography),
('Pharmacie Bourgogne',      'Rue de Bourgogne, Bourgogne',   '+212522000004', FALSE, ST_SetSRID(ST_MakePoint(-7.6400, 33.5950), 4326)::geography),
('Pharmacie Racine',         'Rue Racine, Racine',            '+212522000005', FALSE, ST_SetSRID(ST_MakePoint(-7.6420, 33.5880), 4326)::geography),
('Pharmacie Anfa',           'Bd d''Anfa, Anfa',              '+212522000006', FALSE, ST_SetSRID(ST_MakePoint(-7.6700, 33.5950), 4326)::geography),
('Pharmacie Ain Diab',       'Corniche, Ain Diab',            '+212522000007', TRUE,  ST_SetSRID(ST_MakePoint(-7.6800, 33.5950), 4326)::geography),
('Pharmacie Centre Ville',   'Bd Mohammed V, Centre Ville',   '+212522000008', FALSE, ST_SetSRID(ST_MakePoint(-7.6200, 33.5950), 4326)::geography),
('Pharmacie Habous',         'Quartier des Habous',           '+212522000009', FALSE, ST_SetSRID(ST_MakePoint(-7.6100, 33.5750), 4326)::geography),
('Pharmacie Derb Sultan',    'Derb Sultan',                   '+212522000010', FALSE, ST_SetSRID(ST_MakePoint(-7.6000, 33.5700), 4326)::geography),
('Pharmacie Californie',     'Quartier Californie',           '+212522000011', FALSE, ST_SetSRID(ST_MakePoint(-7.6150, 33.5600), 4326)::geography),
('Pharmacie Oasis',          'Quartier Oasis',                '+212522000012', FALSE, ST_SetSRID(ST_MakePoint(-7.6350, 33.5550), 4326)::geography),
('Pharmacie Hay Hassani',    'Hay Hassani',                   '+212522000013', FALSE, ST_SetSRID(ST_MakePoint(-7.6600, 33.5600), 4326)::geography),
('Pharmacie Sidi Maarouf',   'Sidi Maarouf',                  '+212522000014', TRUE,  ST_SetSRID(ST_MakePoint(-7.6400, 33.5300), 4326)::geography),
('Pharmacie Ain Chock',      'Ain Chock',                     '+212522000015', FALSE, ST_SetSRID(ST_MakePoint(-7.5900, 33.5500), 4326)::geography),
('Pharmacie Belvedere',      'Belvedere',                     '+212522000016', FALSE, ST_SetSRID(ST_MakePoint(-7.5850, 33.5900), 4326)::geography),
('Pharmacie Roches Noires',  'Roches Noires',                 '+212522000017', FALSE, ST_SetSRID(ST_MakePoint(-7.5900, 33.5950), 4326)::geography),
('Pharmacie Ain Sebaa',      'Ain Sebaa',                     '+212522000018', FALSE, ST_SetSRID(ST_MakePoint(-7.5300, 33.6050), 4326)::geography),
('Pharmacie Sbata',          'Sbata',                         '+212522000019', FALSE, ST_SetSRID(ST_MakePoint(-7.5700, 33.5600), 4326)::geography),
('Pharmacie Bouskoura',      'Centre de Bouskoura',           '+212522000020', FALSE, ST_SetSRID(ST_MakePoint(-7.6500, 33.4500), 4326)::geography);
