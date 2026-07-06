-- Screening engine v2: per-LLM-call and per-disposition audit trail
-- (SRS AI Traceability / Explainability / F40).

CREATE TABLE IF NOT EXISTS ai_inference_audit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_no INT NOT NULL,
    call_site VARCHAR(30) NOT NULL,  -- extraction | question | explain | contact | disposition | criteria_upload
    model_name VARCHAR(150),
    prompt_version VARCHAR(30),
    criteria_version_id UUID REFERENCES screening_criteria_versions(id),
    rules_trace JSONB,               -- fired rule ids, question decisions, dispositions
    validator_result JSONB,          -- violations / regenerations when applicable
    ok BOOLEAN NOT NULL DEFAULT TRUE,
    latency_ms INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_inference_audit_session
    ON ai_inference_audit (session_id, turn_no);
CREATE INDEX IF NOT EXISTS idx_ai_inference_audit_created
    ON ai_inference_audit (created_at);
