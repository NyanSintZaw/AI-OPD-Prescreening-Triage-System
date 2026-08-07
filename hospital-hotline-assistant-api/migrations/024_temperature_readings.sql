-- Body-temperature readings captured at the kiosk (BLE thermometer fetch or
-- typed entry). A device row is written the moment the thermometer pushes a
-- measurement — before the patient decides anything — so the reading survives
-- even if they cancel the flow afterwards. session_id is filled in when known
-- and kept (SET NULL) if the session is ever deleted.
--
-- measured_at is server time: the TD1242's on-device clock is not settable
-- over BLE and ships wrong, but readings arrive as live indications at the
-- moment of measurement, so arrival time is the trustworthy timestamp. No
-- dedup index is needed — each indication is a single live event, unlike the
-- polled BP cuff memory.
CREATE TABLE IF NOT EXISTS temperature_readings (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id    UUID REFERENCES sessions(id) ON DELETE SET NULL,
    temperature_c NUMERIC(4,1) NOT NULL CHECK (temperature_c BETWEEN 25 AND 45),
    measured_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source        VARCHAR(10) NOT NULL DEFAULT 'device' CHECK (source IN ('device', 'manual')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_temperature_readings_session_id ON temperature_readings(session_id);
CREATE INDEX IF NOT EXISTS idx_temperature_readings_created_at ON temperature_readings(created_at);
