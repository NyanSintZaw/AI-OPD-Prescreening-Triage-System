-- Migration 006: Doctor profiles and weekly schedule slots
-- Nurses can manage doctor availability; AI uses this to answer patient queries.

CREATE TABLE IF NOT EXISTS doctors (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    department_id UUID REFERENCES departments(id) ON DELETE SET NULL,
    full_name   TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT 'Dr.',
    specialization TEXT,
    phone_ext   TEXT,
    notes       TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_by  UUID REFERENCES admin_users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- day_of_week: 0=Monday, 1=Tuesday, ... 6=Sunday (ISO weekday − 1)
CREATE TABLE IF NOT EXISTS doctor_schedules (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id   UUID NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    day_of_week SMALLINT NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    start_time  TIME NOT NULL,
    end_time    TIME NOT NULL CHECK (end_time > start_time),
    slot_label  TEXT,          -- e.g. "Morning", "Afternoon", "On-Call"
    max_patients SMALLINT,
    is_available BOOLEAN NOT NULL DEFAULT TRUE,
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (doctor_id, day_of_week, start_time)
);

CREATE INDEX IF NOT EXISTS idx_doctors_department   ON doctors(department_id);
CREATE INDEX IF NOT EXISTS idx_doctors_is_active    ON doctors(is_active);
CREATE INDEX IF NOT EXISTS idx_schedules_doctor     ON doctor_schedules(doctor_id);
CREATE INDEX IF NOT EXISTS idx_schedules_day        ON doctor_schedules(day_of_week);
CREATE INDEX IF NOT EXISTS idx_schedules_available  ON doctor_schedules(is_available);

CREATE TRIGGER trg_doctors_updated_at
    BEFORE UPDATE ON doctors
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_doctor_schedules_updated_at
    BEFORE UPDATE ON doctor_schedules
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
