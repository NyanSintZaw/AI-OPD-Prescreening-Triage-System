-- Migration 007: Replace recurring day-of-week slots with specific-date schedule entries.
-- Nurses enter schedules per concrete date (e.g. "Monday 30 Jun").
-- AI always filters to today; old entries are kept for audit/history.

-- Drop the weekly-slot table (no data worth keeping yet) and recreate.
DROP TABLE IF EXISTS doctor_schedules CASCADE;

CREATE TABLE doctor_schedules (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id     UUID NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    schedule_date DATE NOT NULL,
    start_time    TIME NOT NULL,
    end_time      TIME NOT NULL CHECK (end_time > start_time),
    break_start   TIME,
    break_end     TIME,
    room          TEXT,
    slot_label    TEXT,
    is_available  BOOLEAN NOT NULL DEFAULT TRUE,
    notes         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (doctor_id, schedule_date, start_time)
);

CREATE INDEX idx_schedules_doctor    ON doctor_schedules(doctor_id);
CREATE INDEX idx_schedules_date      ON doctor_schedules(schedule_date);
CREATE INDEX idx_schedules_available ON doctor_schedules(is_available);

CREATE TRIGGER trg_doctor_schedules_updated_at
    BEFORE UPDATE ON doctor_schedules
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
