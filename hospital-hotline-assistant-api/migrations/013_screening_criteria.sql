-- Screening engine v2: versioned criteria + per-session engine state,
-- and the specialty OPD departments the MFU routing manual requires.

CREATE TABLE IF NOT EXISTS screening_criteria_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_no INT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'pending_review', 'approved', 'active', 'retired')),
    criteria JSONB NOT NULL,
    source_upload_id UUID NULL,
    change_summary TEXT,
    uploaded_by VARCHAR(100),
    reviewed_by VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ,
    activated_at TIMESTAMPTZ
);

-- exactly one active version at a time
CREATE UNIQUE INDEX IF NOT EXISTS uq_screening_criteria_active
    ON screening_criteria_versions ((TRUE)) WHERE status = 'active';
CREATE UNIQUE INDEX IF NOT EXISTS uq_screening_criteria_version_no
    ON screening_criteria_versions (version_no);

CREATE TABLE IF NOT EXISTS screening_sessions (
    session_id UUID PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    state JSONB NOT NULL,
    criteria_version_id UUID REFERENCES screening_criteria_versions(id),
    prompt_version TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Specialty departments from the MFU routing manual (surgery, eye,
-- psychiatry, OB-GYN). Forensic cases route to the emergency department.
INSERT INTO departments (code, kind, name_en, name_th, description_en, description_th, is_active)
VALUES
    ('opd_surgery', 'opd', 'OPD Surgery', 'OPD ศัลยกรรม', 'OPD clinic for surgical concerns (lumps, wounds, scars, anorectal, vascular).', 'คลินิก OPD ศัลยกรรม (ก้อน แผล แผลเป็น ทวารหนัก หลอดเลือด)', TRUE),
    ('opd_ophthalmology', 'opd', 'OPD Ophthalmology', 'OPD จักษุ', 'OPD clinic for eye concerns.', 'คลินิก OPD สำหรับอาการทางตา', TRUE),
    ('opd_psychiatry', 'opd', 'OPD Psychiatry', 'OPD จิตเวช', 'OPD clinic for mental health concerns.', 'คลินิก OPD สำหรับปัญหาสุขภาพจิต', TRUE),
    ('opd_obgyn', 'opd', 'OPD Obstetrics & Gynecology', 'OPD สูตินรีเวช', 'OPD clinic for pregnancy and gynecological concerns.', 'คลินิก OPD สำหรับการตั้งครรภ์และโรคทางนรีเวช', TRUE)
ON CONFLICT (code) DO UPDATE
SET
    kind = EXCLUDED.kind,
    name_en = EXCLUDED.name_en,
    name_th = EXCLUDED.name_th,
    description_en = EXCLUDED.description_en,
    description_th = EXCLUDED.description_th,
    is_active = EXCLUDED.is_active;
