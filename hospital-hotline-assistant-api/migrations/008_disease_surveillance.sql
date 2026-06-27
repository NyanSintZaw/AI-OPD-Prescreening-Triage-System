-- Add optional patient-reported area to sessions
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS location_area VARCHAR(100);
CREATE INDEX IF NOT EXISTS idx_sessions_location_area ON sessions(location_area);

-- Disease surveillance table: one row per triage classification event.
-- symptom_keywords holds normalised tags (red_flags + symptoms_summary text).
CREATE TABLE IF NOT EXISTS disease_surveillance (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id    UUID         NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    symptom_keywords TEXT[]   NOT NULL DEFAULT ARRAY[]::TEXT[],
    symptoms_summary TEXT,
    severity_level   VARCHAR(20),
    location_area    VARCHAR(100),
    reported_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ds_session_id    ON disease_surveillance(session_id);
CREATE INDEX IF NOT EXISTS idx_ds_reported_at   ON disease_surveillance(reported_at);
CREATE INDEX IF NOT EXISTS idx_ds_location_area ON disease_surveillance(location_area);
CREATE INDEX IF NOT EXISTS idx_ds_keywords      ON disease_surveillance USING GIN(symptom_keywords);
