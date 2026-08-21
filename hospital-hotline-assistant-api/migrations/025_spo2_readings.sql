-- SpO2 + pulse readings captured at the kiosk (Rossmax SB210 fingertip
-- pulse oximeter fetch, or a typed entry). A device row is written the
-- moment a settled reading arrives — before the patient decides anything —
-- so the measurement survives even if they cancel the flow afterwards.
-- session_id is filled in when known and kept (SET NULL) if the session is
-- ever deleted.
--
-- measured_at is server time: the SB210 streams packets live, so arrival
-- time is the measurement time. No dedup index is needed — each fetch is a
-- single live sampling window, unlike the polled BP cuff memory.
CREATE TABLE IF NOT EXISTS spo2_readings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID REFERENCES sessions(id) ON DELETE SET NULL,
    spo2        SMALLINT NOT NULL CHECK (spo2 BETWEEN 50 AND 100),
    pulse_bpm   SMALLINT CHECK (pulse_bpm BETWEEN 20 AND 250),
    measured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source      VARCHAR(10) NOT NULL DEFAULT 'device' CHECK (source IN ('device', 'manual')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_spo2_readings_session_id ON spo2_readings(session_id);
CREATE INDEX IF NOT EXISTS idx_spo2_readings_created_at ON spo2_readings(created_at);
