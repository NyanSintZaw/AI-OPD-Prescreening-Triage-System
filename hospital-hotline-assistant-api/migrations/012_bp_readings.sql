-- Blood-pressure readings captured at the kiosk (cuff fetch or manual entry).
-- A row is written the moment a cuff read succeeds — before the patient
-- decides anything — so the reading survives even if they cancel the
-- voice/chat flow afterwards. session_id is filled in when known and kept
-- (SET NULL) if the session is ever deleted.
--
-- measured_at is TIMESTAMP (no tz): it is the cuff's own clock, which runs
-- in device-local time; the freshness check compares it to server local time.
CREATE TABLE IF NOT EXISTS bp_readings (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id          UUID REFERENCES sessions(id) ON DELETE SET NULL,
    systolic            SMALLINT NOT NULL CHECK (systolic BETWEEN 40 AND 300),
    diastolic           SMALLINT NOT NULL CHECK (diastolic BETWEEN 20 AND 200),
    pulse_bpm           SMALLINT CHECK (pulse_bpm IS NULL OR pulse_bpm BETWEEN 20 AND 250),
    measured_at         TIMESTAMP,
    irregular_heartbeat BOOLEAN,
    body_movement       BOOLEAN,
    source              VARCHAR(10) NOT NULL DEFAULT 'device' CHECK (source IN ('device', 'manual')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bp_readings_session_id ON bp_readings(session_id);
CREATE INDEX IF NOT EXISTS idx_bp_readings_created_at ON bp_readings(created_at);

-- The kiosk polls the cuff while waiting for a fresh measurement, so the
-- same physical reading can be fetched several times; store it only once.
CREATE UNIQUE INDEX IF NOT EXISTS uq_bp_readings_device_measurement
    ON bp_readings(measured_at, systolic, diastolic)
    WHERE source = 'device';
