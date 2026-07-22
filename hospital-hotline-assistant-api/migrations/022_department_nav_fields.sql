-- Floor / room / nav-hint columns for short patient-slip wayfinding text.
ALTER TABLE departments
    ADD COLUMN IF NOT EXISTS floor VARCHAR(50),
    ADD COLUMN IF NOT EXISTS room VARCHAR(100),
    ADD COLUMN IF NOT EXISTS nav_hint_en TEXT,
    ADD COLUMN IF NOT EXISTS nav_hint_th TEXT;

-- Demo MFU-style floors (content can be refined with hospital facilities).
-- GP already encodes "ชั้น1" in the HIS name; ENT example from the meeting
-- is 3rd Floor.
UPDATE departments SET floor = '1', room = 'ER' WHERE code = 'emergency';
UPDATE departments SET floor = '1' WHERE code = 'opd_general';
UPDATE departments SET floor = '2' WHERE code = 'opd_internal_medicine';
UPDATE departments SET floor = '2' WHERE code = 'opd_pediatrics';
UPDATE departments SET floor = '2' WHERE code = 'opd_cardiology';
UPDATE departments SET floor = '1' WHERE code = 'opd_orthopedics';
UPDATE departments SET floor = '3' WHERE code = 'opd_ent';
UPDATE departments SET floor = '2' WHERE code = 'opd_surgery';
UPDATE departments SET floor = '3' WHERE code = 'opd_ophthalmology';
UPDATE departments SET floor = '3' WHERE code = 'opd_psychiatry';
UPDATE departments SET floor = '2' WHERE code = 'opd_obgyn';
