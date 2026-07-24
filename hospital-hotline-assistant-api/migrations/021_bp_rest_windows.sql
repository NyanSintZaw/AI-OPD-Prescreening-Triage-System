-- BP re-measure rest windows: after a hypertensive-crisis reading the patient
-- must rest 15 minutes before another cuff/manual BP is accepted. Keyed by HN
-- (preferred) or visit_id so the timer survives intervening kiosk patients.
CREATE TABLE IF NOT EXISTS bp_rest_windows (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hn                   TEXT,
    visit_id             TEXT,
    triggered_by_reading UUID REFERENCES bp_readings(id) ON DELETE SET NULL,
    rest_until           TIMESTAMPTZ NOT NULL,
    reason               VARCHAR(50) NOT NULL DEFAULT 'hypertensive_crisis',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at          TIMESTAMPTZ,
    CHECK (hn IS NOT NULL OR visit_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_bp_rest_windows_hn ON bp_rest_windows(hn);
CREATE INDEX IF NOT EXISTS idx_bp_rest_windows_visit_id ON bp_rest_windows(visit_id);
CREATE INDEX IF NOT EXISTS idx_bp_rest_windows_active
    ON bp_rest_windows (rest_until)
    WHERE resolved_at IS NULL;
