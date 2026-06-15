DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'department_kind') THEN
        CREATE TYPE department_kind AS ENUM ('emergency', 'opd');
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'review_status') THEN
        CREATE TYPE review_status AS ENUM ('pending', 'approved', 'corrected');
    END IF;
END
$$;

ALTER TABLE departments
ADD COLUMN IF NOT EXISTS kind department_kind NOT NULL DEFAULT 'opd';

UPDATE departments
SET kind = CASE
    WHEN code = 'emergency' THEN 'emergency'::department_kind
    ELSE 'opd'::department_kind
END;

INSERT INTO departments (code, kind, name_en, name_th, description_en, description_th, is_active)
VALUES
    ('emergency', 'emergency', 'Emergency Department', 'แผนกฉุกเฉิน', 'Immediate life-threatening situations.', 'สำหรับภาวะฉุกเฉินที่เป็นอันตรายต่อชีวิต', TRUE),
    ('opd_general', 'opd', 'OPD General Practice', 'OPD เวชปฏิบัติทั่วไป', 'First-stop OPD for general symptoms and triage follow-up.', 'จุดคัดกรอง OPD แรกสำหรับอาการทั่วไปและการติดตามผล', TRUE),
    ('opd_internal_medicine', 'opd', 'OPD Internal Medicine', 'OPD อายุรกรรม', 'OPD clinic for adult internal medicine concerns.', 'คลินิก OPD สำหรับอายุรกรรมผู้ใหญ่', TRUE),
    ('opd_pediatrics', 'opd', 'OPD Pediatrics', 'OPD กุมารเวชกรรม', 'OPD clinic for children and adolescents.', 'คลินิก OPD สำหรับเด็กและวัยรุ่น', TRUE),
    ('opd_cardiology', 'opd', 'OPD Cardiology', 'OPD โรคหัวใจ', 'OPD clinic for non-emergency heart-related symptoms.', 'คลินิก OPD สำหรับอาการโรคหัวใจที่ไม่ฉุกเฉิน', TRUE),
    ('opd_orthopedics', 'opd', 'OPD Orthopedics', 'OPD กระดูกและข้อ', 'OPD clinic for musculoskeletal concerns.', 'คลินิก OPD สำหรับปัญหากระดูก กล้ามเนื้อ และข้อ', TRUE),
    ('opd_ent', 'opd', 'OPD ENT', 'OPD หู คอ จมูก', 'OPD clinic for ear, nose, and throat concerns.', 'คลินิก OPD สำหรับอาการหู คอ จมูก', TRUE)
ON CONFLICT (code) DO UPDATE
SET
    kind = EXCLUDED.kind,
    name_en = EXCLUDED.name_en,
    name_th = EXCLUDED.name_th,
    description_en = EXCLUDED.description_en,
    description_th = EXCLUDED.description_th,
    is_active = EXCLUDED.is_active,
    updated_at = NOW();

UPDATE departments
SET is_active = FALSE
WHERE code IN (
    'general_medicine',
    'pediatrics',
    'cardiology',
    'orthopedics',
    'ent'
);

UPDATE routing_rules
SET is_active = FALSE
WHERE is_active = TRUE;

INSERT INTO routing_rules (
    department_id,
    rule_name,
    description,
    symptom_keywords,
    condition_json,
    severity_override,
    priority,
    is_active
)
SELECT
    d.id,
    'OPD chest discomfort without emergency signs',
    'Default OPD routing for chest discomfort cases that are not emergency-triggered.',
    ARRAY['chest discomfort', 'mild chest pain', 'palpitations'],
    '{"any":["chest discomfort","mild chest pain","palpitations"]}'::jsonb,
    NULL,
    40,
    TRUE
FROM departments d
WHERE d.code = 'opd_cardiology'
ON CONFLICT DO NOTHING;

INSERT INTO routing_rules (
    department_id,
    rule_name,
    description,
    symptom_keywords,
    condition_json,
    severity_override,
    priority,
    is_active
)
SELECT
    d.id,
    'OPD ENT symptoms',
    'OPD-first routing for ENT symptom cluster.',
    ARRAY['ear pain', 'sore throat', 'runny nose', 'hearing problem', 'sinus'],
    '{"any":["ear pain","sore throat","runny nose","hearing problem","sinus"]}'::jsonb,
    'general',
    50,
    TRUE
FROM departments d
WHERE d.code = 'opd_ent'
ON CONFLICT DO NOTHING;

INSERT INTO routing_rules (
    department_id,
    rule_name,
    description,
    symptom_keywords,
    condition_json,
    severity_override,
    priority,
    is_active
)
SELECT
    d.id,
    'OPD general symptoms',
    'Default OPD-first routing for non-specific symptoms.',
    ARRAY['fever', 'cough', 'fatigue', 'headache', 'nausea'],
    '{"any":["fever","cough","fatigue","headache","nausea"]}'::jsonb,
    'general',
    90,
    TRUE
FROM departments d
WHERE d.code = 'opd_general'
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS assessment_reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    assessment_id UUID NOT NULL UNIQUE REFERENCES severity_assessments(id) ON DELETE CASCADE,
    reviewer_id UUID REFERENCES admin_users(id) ON DELETE SET NULL,
    status review_status NOT NULL DEFAULT 'pending',
    proposed_department_id UUID REFERENCES departments(id) ON DELETE SET NULL,
    confirmed_department_id UUID REFERENCES departments(id) ON DELETE SET NULL,
    notes TEXT,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_assessment_reviews_status ON assessment_reviews(status);
CREATE INDEX IF NOT EXISTS idx_assessment_reviews_session_id ON assessment_reviews(session_id);
CREATE INDEX IF NOT EXISTS idx_assessment_reviews_reviewer_id ON assessment_reviews(reviewer_id);
CREATE TRIGGER trg_assessment_reviews_updated_at BEFORE UPDATE ON assessment_reviews FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS routing_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    assessment_id UUID REFERENCES severity_assessments(id) ON DELETE CASCADE,
    original_department_id UUID REFERENCES departments(id) ON DELETE SET NULL,
    corrected_department_id UUID NOT NULL REFERENCES departments(id) ON DELETE RESTRICT,
    reported_by UUID REFERENCES admin_users(id) ON DELETE SET NULL,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE routing_feedback
ADD COLUMN IF NOT EXISTS assessment_id UUID REFERENCES severity_assessments(id) ON DELETE CASCADE;

ALTER TABLE routing_feedback
ADD COLUMN IF NOT EXISTS reported_by UUID REFERENCES admin_users(id) ON DELETE SET NULL;

ALTER TABLE routing_feedback
ADD COLUMN IF NOT EXISTS reason TEXT;

ALTER TABLE routing_feedback
ADD COLUMN IF NOT EXISTS assessment_result_id UUID;

ALTER TABLE routing_feedback
ADD COLUMN IF NOT EXISTS nurse_user_id UUID REFERENCES admin_users(id) ON DELETE SET NULL;

ALTER TABLE routing_feedback
ADD COLUMN IF NOT EXISTS feedback_text TEXT;

ALTER TABLE routing_feedback
ADD COLUMN IF NOT EXISTS original_urgency severity_level;

ALTER TABLE routing_feedback
ADD COLUMN IF NOT EXISTS corrected_urgency severity_level;

ALTER TABLE routing_feedback
ALTER COLUMN assessment_result_id DROP NOT NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'routing_feedback' AND column_name = 'assessment_result_id'
    ) THEN
        EXECUTE '
            UPDATE routing_feedback
            SET assessment_id = COALESCE(assessment_id, assessment_result_id)
        ';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'routing_feedback' AND column_name = 'nurse_user_id'
    ) THEN
        EXECUTE '
            UPDATE routing_feedback
            SET reported_by = COALESCE(reported_by, nurse_user_id)
        ';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'routing_feedback' AND column_name = 'feedback_text'
    ) THEN
        EXECUTE '
            UPDATE routing_feedback
            SET reason = COALESCE(reason, feedback_text)
        ';
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_routing_feedback_session_id ON routing_feedback(session_id);
CREATE INDEX IF NOT EXISTS idx_routing_feedback_assessment_id ON routing_feedback(assessment_id);
CREATE INDEX IF NOT EXISTS idx_routing_feedback_reported_by ON routing_feedback(reported_by);

INSERT INTO admin_users (email, password_hash, full_name, role, is_active)
VALUES (
    'opd.nurse@mfu.local',
    'sha256$' || encode(digest('nurse1234', 'sha256'), 'hex'),
    'OPD Nurse (Seed)',
    'admin',
    TRUE
)
ON CONFLICT (email) DO NOTHING;
