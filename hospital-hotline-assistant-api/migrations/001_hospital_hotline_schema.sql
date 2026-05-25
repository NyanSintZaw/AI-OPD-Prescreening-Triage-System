CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE language_code AS ENUM ('th', 'en');
CREATE TYPE session_status AS ENUM ('active', 'completed', 'reset', 'escalated');
CREATE TYPE message_role AS ENUM ('user', 'assistant', 'system');
CREATE TYPE input_mode AS ENUM ('voice', 'text');
CREATE TYPE severity_level AS ENUM ('emergency', 'urgent', 'general', 'unknown');
CREATE TYPE admin_role AS ENUM ('super_admin', 'admin', 'viewer');

CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    language language_code NOT NULL DEFAULT 'th',
    status session_status NOT NULL DEFAULT 'active',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    user_agent TEXT,
    ip_hash TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role message_role NOT NULL,
    input_mode input_mode,
    content TEXT NOT NULL,
    audio_url TEXT,
    transcript_confidence NUMERIC(5,4) CHECK (transcript_confidence IS NULL OR transcript_confidence BETWEEN 0 AND 1),
    model_name TEXT,
    response_latency_ms INTEGER CHECK (response_latency_ms IS NULL OR response_latency_ms >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE symptom_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
    raw_text TEXT NOT NULL,
    normalized_symptoms JSONB NOT NULL DEFAULT '[]'::jsonb,
    body_location TEXT,
    duration_text TEXT,
    pain_score SMALLINT CHECK (pain_score IS NULL OR pain_score BETWEEN 0 AND 10),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE follow_up_questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    question_text TEXT NOT NULL,
    reason TEXT,
    asked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    answer_message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
    answered_at TIMESTAMPTZ
);

CREATE TABLE severity_assessments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    source_message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
    severity severity_level NOT NULL DEFAULT 'unknown',
    confidence NUMERIC(5,4) CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    explanation TEXT,
    detected_triggers JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE departments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(50) NOT NULL UNIQUE,
    name_en VARCHAR(150) NOT NULL,
    name_th VARCHAR(150),
    description_en TEXT,
    description_th TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE admin_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name VARCHAR(150),
    role admin_role NOT NULL DEFAULT 'viewer',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE routing_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    department_id UUID NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    rule_name VARCHAR(150) NOT NULL,
    description TEXT,
    symptom_keywords TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    condition_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    severity_override severity_level,
    priority INTEGER NOT NULL DEFAULT 100,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID REFERENCES admin_users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES admin_users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE emergency_triggers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_name VARCHAR(150) NOT NULL,
    description TEXT,
    trigger_keywords TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    condition_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    alert_message_en TEXT NOT NULL,
    alert_message_th TEXT,
    priority INTEGER NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID REFERENCES admin_users(id) ON DELETE SET NULL,
    updated_by UUID REFERENCES admin_users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE department_recommendations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    assessment_id UUID REFERENCES severity_assessments(id) ON DELETE SET NULL,
    department_id UUID NOT NULL REFERENCES departments(id) ON DELETE RESTRICT,
    confidence NUMERIC(5,4) CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE emergency_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    trigger_id UUID REFERENCES emergency_triggers(id) ON DELETE SET NULL,
    source_message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
    detected_symptoms JSONB NOT NULL DEFAULT '[]'::jsonb,
    alert_message TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_user_id UUID REFERENCES admin_users(id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,
    entity_type VARCHAR(100) NOT NULL,
    entity_id UUID,
    before_data JSONB,
    after_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sessions_started_at ON sessions(started_at);
CREATE INDEX idx_sessions_status ON sessions(status);
CREATE INDEX idx_messages_session_id ON messages(session_id);
CREATE INDEX idx_messages_session_created_at ON messages(session_id, created_at);
CREATE INDEX idx_messages_role ON messages(role);
CREATE INDEX idx_symptom_entries_session_id ON symptom_entries(session_id);
CREATE INDEX idx_symptom_entries_normalized_symptoms ON symptom_entries USING GIN(normalized_symptoms);
CREATE INDEX idx_follow_up_questions_session_id ON follow_up_questions(session_id);
CREATE INDEX idx_severity_assessments_session_id ON severity_assessments(session_id);
CREATE INDEX idx_severity_assessments_severity ON severity_assessments(severity);
CREATE INDEX idx_severity_assessments_created_at ON severity_assessments(created_at);
CREATE INDEX idx_departments_code ON departments(code);
CREATE INDEX idx_departments_is_active ON departments(is_active);
CREATE INDEX idx_admin_users_email ON admin_users(email);
CREATE INDEX idx_admin_users_role ON admin_users(role);
CREATE INDEX idx_routing_rules_department_id ON routing_rules(department_id);
CREATE INDEX idx_routing_rules_is_active ON routing_rules(is_active);
CREATE INDEX idx_routing_rules_priority ON routing_rules(priority);
CREATE INDEX idx_routing_rules_symptom_keywords ON routing_rules USING GIN(symptom_keywords);
CREATE INDEX idx_routing_rules_condition_json ON routing_rules USING GIN(condition_json);
CREATE INDEX idx_emergency_triggers_is_active ON emergency_triggers(is_active);
CREATE INDEX idx_emergency_triggers_priority ON emergency_triggers(priority);
CREATE INDEX idx_emergency_triggers_keywords ON emergency_triggers USING GIN(trigger_keywords);
CREATE INDEX idx_emergency_triggers_condition_json ON emergency_triggers USING GIN(condition_json);
CREATE INDEX idx_department_recommendations_session_id ON department_recommendations(session_id);
CREATE INDEX idx_department_recommendations_department_id ON department_recommendations(department_id);
CREATE INDEX idx_emergency_events_session_id ON emergency_events(session_id);
CREATE INDEX idx_emergency_events_trigger_id ON emergency_events(trigger_id);
CREATE INDEX idx_emergency_events_created_at ON emergency_events(created_at);
CREATE INDEX idx_audit_logs_admin_user_id ON audit_logs(admin_user_id);
CREATE INDEX idx_audit_logs_entity ON audit_logs(entity_type, entity_id);
CREATE INDEX idx_audit_logs_created_at ON audit_logs(created_at);

CREATE VIEW conversation_summary AS
SELECT
    s.id AS session_id,
    s.language,
    s.status,
    s.started_at,
    s.ended_at,
    latest_assessment.severity,
    latest_recommendation.department_name_en,
    latest_recommendation.department_name_th,
    COUNT(m.id) AS message_count
FROM sessions s
LEFT JOIN messages m ON m.session_id = s.id
LEFT JOIN LATERAL (
    SELECT sa.severity
    FROM severity_assessments sa
    WHERE sa.session_id = s.id
    ORDER BY sa.created_at DESC
    LIMIT 1
) latest_assessment ON TRUE
LEFT JOIN LATERAL (
    SELECT d.name_en AS department_name_en, d.name_th AS department_name_th
    FROM department_recommendations dr
    JOIN departments d ON d.id = dr.department_id
    WHERE dr.session_id = s.id
    ORDER BY dr.created_at DESC
    LIMIT 1
) latest_recommendation ON TRUE
GROUP BY
    s.id,
    s.language,
    s.status,
    s.started_at,
    s.ended_at,
    latest_assessment.severity,
    latest_recommendation.department_name_en,
    latest_recommendation.department_name_th;

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_departments_updated_at BEFORE UPDATE ON departments FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_admin_users_updated_at BEFORE UPDATE ON admin_users FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_routing_rules_updated_at BEFORE UPDATE ON routing_rules FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_emergency_triggers_updated_at BEFORE UPDATE ON emergency_triggers FOR EACH ROW EXECUTE FUNCTION set_updated_at();

INSERT INTO departments (code, name_en, name_th, description_en) VALUES
('emergency', 'Emergency Department', 'แผนกฉุกเฉิน', 'For life-threatening or urgent medical situations.'),
('general_medicine', 'General Medicine', 'อายุรกรรมทั่วไป', 'For general adult medical symptoms.'),
('pediatrics', 'Pediatrics', 'กุมารเวชกรรม', 'For children and adolescent patients.'),
('cardiology', 'Cardiology', 'โรคหัวใจ', 'For heart-related symptoms.'),
('orthopedics', 'Orthopedics', 'กระดูกและข้อ', 'For bone, joint, muscle, or injury-related symptoms.'),
('ent', 'ENT', 'หู คอ จมูก', 'For ear, nose, and throat symptoms.');

INSERT INTO emergency_triggers (trigger_name, description, trigger_keywords, condition_json, alert_message_en, alert_message_th, priority) VALUES
('Chest pain with breathing difficulty', 'Possible serious heart or respiratory emergency.', ARRAY['chest pain', 'breathing difficulty', 'shortness of breath'], '{"all":["chest pain"],"any":["breathing difficulty","shortness of breath"]}'::jsonb, 'This may be an emergency. Please seek immediate medical care or contact emergency services.', 'อาการนี้อาจเป็นภาวะฉุกเฉิน กรุณารีบไปพบแพทย์ทันทีหรือติดต่อหน่วยฉุกเฉิน', 1),
('Loss of consciousness', 'User reports fainting or unconsciousness.', ARRAY['loss of consciousness', 'unconscious', 'fainting'], '{"any":["loss of consciousness","unconscious","fainting"]}'::jsonb, 'Loss of consciousness may be an emergency. Please seek immediate medical care.', 'หมดสติหรือเป็นลมอาจเป็นภาวะฉุกเฉิน กรุณารีบไปพบแพทย์ทันที', 1),
('Severe bleeding', 'User reports severe bleeding.', ARRAY['severe bleeding', 'heavy bleeding', 'bleeding a lot'], '{"any":["severe bleeding","heavy bleeding","bleeding a lot"]}'::jsonb, 'Severe bleeding may be an emergency. Please seek immediate medical care.', 'เลือดออกมากอาจเป็นภาวะฉุกเฉิน กรุณารีบไปพบแพทย์ทันที', 1);

INSERT INTO routing_rules (department_id, rule_name, symptom_keywords, condition_json, severity_override, priority)
SELECT id, 'Chest pain with breathing symptoms', ARRAY['chest pain', 'breathing difficulty', 'shortness of breath'], '{"all":["chest pain"],"any":["breathing difficulty","shortness of breath"]}'::jsonb, 'emergency', 1
FROM departments WHERE code = 'emergency';

INSERT INTO routing_rules (department_id, rule_name, symptom_keywords, condition_json, severity_override, priority)
SELECT id, 'Ear nose throat symptoms', ARRAY['ear pain', 'sore throat', 'runny nose', 'hearing problem'], '{"any":["ear pain","sore throat","runny nose","hearing problem"]}'::jsonb, 'general', 50
FROM departments WHERE code = 'ent';
