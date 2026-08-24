-- HN-first identity (Data Requirements V1, 2026-08-11): the kiosk flow
-- starts from the patient's HN; session lookup is by
-- metadata->'patient'->>'hn'. The VN is a nullable passthrough inside the
-- same block and never an identity. Dev data is wiped with this release
-- (docker compose down -v), so no data migration of old metadata.visit
-- blobs is attempted.

DROP INDEX IF EXISTS idx_sessions_visit_id;
CREATE INDEX IF NOT EXISTS idx_sessions_patient_hn
    ON sessions ((metadata->'patient'->>'hn'))
    WHERE metadata->'patient'->>'hn' IS NOT NULL;

-- bp_rest_windows: HN-only keying (the VN leg is gone with VN identity).
-- Recreate rather than ALTER: 021's inline CHECK is unnamed and the table's
-- dev data is wiped anyway. Anonymous sessions never open a window.
DROP TABLE IF EXISTS bp_rest_windows;
CREATE TABLE bp_rest_windows (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hn                   TEXT NOT NULL,
    triggered_by_reading UUID REFERENCES bp_readings(id) ON DELETE SET NULL,
    rest_until           TIMESTAMPTZ NOT NULL,
    reason               VARCHAR(50) NOT NULL DEFAULT 'hypertensive_crisis',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at          TIMESTAMPTZ
);
CREATE INDEX idx_bp_rest_windows_hn ON bp_rest_windows(hn);
CREATE INDEX idx_bp_rest_windows_active
    ON bp_rest_windows (rest_until) WHERE resolved_at IS NULL;
