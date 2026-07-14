-- Align our department records with the hospital's real HIS department
-- names (verbatim from the MFU prescreen export), so nurse dropdowns, the
-- patient recommendation card, and the write-back all reference names the
-- hospital and its staff recognize.
--
-- name_th is set to the exact HIS string (matches
-- app/services/screening/his/department_map.py CODE_TO_HIS); name_en stays
-- the clean English label used in patient-facing reply templates.
-- Idempotent: only updates existing rows by code.

UPDATE departments SET name_th = 'แผนก ER (อุบัติเหตุและฉุกเฉิน)'          WHERE code = 'emergency';
UPDATE departments SET name_th = 'แผนก OPD GP (ทั่วไป ชั้น1)'              WHERE code = 'opd_general';
UPDATE departments SET name_th = 'แผนก OPD MED (อายุรกรรม)'               WHERE code = 'opd_internal_medicine';
UPDATE departments SET name_th = 'แผนก OPD PEDIATRIC (กุมารเวชกรรม)'       WHERE code = 'opd_pediatrics';
UPDATE departments SET name_th = 'แผนก OPD HEART (หน่วยตรวจหัวใจและหลอดเลือด)' WHERE code = 'opd_cardiology';
UPDATE departments SET name_th = 'แผนก OPD ORTHOPEDIC (โรคกระดูกและข้อ)'   WHERE code = 'opd_orthopedics';
UPDATE departments SET name_th = 'แผนก OPD E.N.T (หู คอ จมูก)'            WHERE code = 'opd_ent';
UPDATE departments SET name_th = 'แผนก OPD SURGICAL (ศัลยศาสตร์)'          WHERE code = 'opd_surgery';
UPDATE departments SET name_th = 'แผนก OPD EYE (ตา)'                      WHERE code = 'opd_ophthalmology';
UPDATE departments SET name_th = 'แผนก จิตเวช'                            WHERE code = 'opd_psychiatry';
UPDATE departments SET name_th = 'แผนก OPD OB-GYN (สูติ-นรีเวชกรรม)'       WHERE code = 'opd_obgyn';
