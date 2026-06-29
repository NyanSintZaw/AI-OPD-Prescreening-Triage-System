-- Track metadata for each triage-manual PDF upload.
-- One row per upload; the latest row with status='ready' is the active manual.
CREATE TABLE IF NOT EXISTS triage_manual_uploads (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    original_filename VARCHAR(255) NOT NULL,
    file_size_bytes BIGINT,
    chunks_count    INT,
    status          VARCHAR(20) NOT NULL DEFAULT 'processing',
    error_message   TEXT,
    uploaded_by     VARCHAR(100),
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tmu_uploaded_at ON triage_manual_uploads(uploaded_at DESC);
CREATE INDEX IF NOT EXISTS idx_tmu_status      ON triage_manual_uploads(status);
