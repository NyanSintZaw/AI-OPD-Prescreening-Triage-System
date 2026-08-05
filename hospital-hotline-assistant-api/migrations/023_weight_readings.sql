-- Weight readings captured at the kiosk (Omron HBF-222T scale or manual
-- entry). Mirrors bp_readings: a row is written the moment a scale read
-- succeeds — before the patient decides anything — so the measurement
-- survives even if they cancel the flow afterwards. session_id is filled in
-- when known and kept (SET NULL) if the session is ever deleted.
--
-- measured_at is TIMESTAMP (no tz): it is the scale's own clock, which
-- resets on battery change — sequence (the scale's per-user monotonic
-- counter) is the reliable identity/novelty signal, so device rows dedupe
-- on it.
CREATE TABLE IF NOT EXISTS weight_readings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID REFERENCES sessions(id) ON DELETE SET NULL,
    weight_kg   NUMERIC(5,1) NOT NULL CHECK (weight_kg > 0 AND weight_kg <= 400),
    sequence    INTEGER,
    measured_at TIMESTAMP,
    source      VARCHAR(10) NOT NULL DEFAULT 'device' CHECK (source IN ('device', 'manual')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_weight_readings_session_id ON weight_readings(session_id);
CREATE INDEX IF NOT EXISTS idx_weight_readings_created_at ON weight_readings(created_at);

-- The kiosk polls while waiting for a sync, so the same physical
-- measurement can be fetched several times; store it only once.
CREATE UNIQUE INDEX IF NOT EXISTS uq_weight_readings_device_sequence
    ON weight_readings(sequence)
    WHERE source = 'device' AND sequence IS NOT NULL;
