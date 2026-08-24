import logging
from datetime import date
from uuid import UUID
import asyncpg
from fastapi import (
    Depends,
    HTTPException,
    status,
)
from app.database import get_connection, records_to_dicts

logger = logging.getLogger(__name__)
from app.schemas import (
    DepartmentOut,
    DoctorCreate,
    DoctorOut,
    DoctorScheduleCreate,
    DoctorScheduleOut,
    DoctorUpdate,
    DoctorWithSchedulesOut,
    EmergencyTriggerOut,
    RoutingRuleOut,
)

from fastapi import APIRouter
from app.routers.deps import require_roles

router = APIRouter()

@router.get("/departments", response_model=list[DepartmentOut])
async def list_departments(connection: asyncpg.Connection = Depends(get_connection)):
    from app.services.screening import templates as screening_templates

    records = await connection.fetch(
        "SELECT * FROM departments WHERE is_active = TRUE ORDER BY name_en ASC"
    )
    out: list[dict] = []
    for record in records:
        row = dict(record)
        name_en = row.get("name_en") or row.get("code") or ""
        name_th = row.get("name_th") or name_en
        floor = row.get("floor")
        room = row.get("room")
        row["nav_line_en"] = screening_templates.nav_line(
            name_en,
            language="en",
            floor=floor,
            room=room,
            nav_hint=row.get("nav_hint_en"),
        )
        row["nav_line_th"] = screening_templates.nav_line(
            name_th,
            language="th",
            floor=floor,
            room=room,
            nav_hint=row.get("nav_hint_th"),
        )
        out.append(row)
    return out

@router.get("/routing-rules", response_model=list[RoutingRuleOut])
async def list_routing_rules(connection: asyncpg.Connection = Depends(get_connection)):
    records = await connection.fetch(
        "SELECT * FROM routing_rules WHERE is_active = TRUE ORDER BY priority ASC, rule_name ASC"
    )
    return records_to_dicts(records)

@router.get("/emergency-triggers", response_model=list[EmergencyTriggerOut])
async def list_emergency_triggers(connection: asyncpg.Connection = Depends(get_connection)):
    records = await connection.fetch(
        "SELECT * FROM emergency_triggers WHERE is_active = TRUE ORDER BY priority ASC, trigger_name ASC"
    )
    return records_to_dicts(records)
@router.get("/kiosk/stats")
async def kiosk_stats(connection: asyncpg.Connection = Depends(get_connection)) -> dict:
    """Public counters for the kiosk home / attract screen (no auth).

    Three "today" numbers the booth shows patients:
      - ``booth_patients_today`` : distinct patients (by linked HN) who
                              used this booth today. Counted from our own
                              sessions — deliberately NOT from the hospital:
                              this endpoint is unauthenticated, and asking the
                              HIS would mean enumerating their whole visit
                              list on every anonymous kiosk hit.
      - ``navigated_today`` : nurse-approved/corrected assessments today.
      - ``sessions_today``  : triage sessions started at the booth today.
    Every source degrades to 0 rather than erroring so the screen never breaks.
    """
    today = date.today()

    try:
        sessions_today = await connection.fetchval(
            "SELECT count(*) FROM sessions WHERE started_at::date = CURRENT_DATE"
        )
    except Exception:  # pragma: no cover - defensive: never break the kiosk
        sessions_today = 0

    try:
        navigated_today = await connection.fetchval(
            """
            SELECT count(*) FROM assessment_reviews
            WHERE status IN ('approved', 'corrected')
              AND reviewed_at::date = CURRENT_DATE
            """
        )
    except Exception:  # pragma: no cover
        navigated_today = 0

    try:
        booth_patients_today = await connection.fetchval(
            """
            SELECT count(DISTINCT metadata->'patient'->>'hn')
            FROM sessions
            WHERE started_at::date = CURRENT_DATE
              AND metadata->'patient'->>'hn' IS NOT NULL
            """
        )
    except Exception:  # pragma: no cover - defensive: never break the kiosk
        booth_patients_today = 0

    return {
        "date": today.isoformat(),
        "booth_patients_today": int(booth_patients_today or 0),
        "navigated_today": int(navigated_today or 0),
        "sessions_today": int(sessions_today or 0),
    }

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _doctor_row_to_out(row: dict, dept_row: dict | None = None) -> dict:
    return {
        **row,
        "department_name_en": dept_row["name_en"] if dept_row else None,
        "department_name_th": dept_row["name_th"] if dept_row else None,
    }


@router.get("/doctors", response_model=list[DoctorOut])
async def list_doctors(
    active_only: bool = True,
    connection: asyncpg.Connection = Depends(get_connection),
):
    """List all doctors, optionally filtering by active status."""
    rows = await connection.fetch(
        """
        SELECT d.*, dept.name_en AS department_name_en, dept.name_th AS department_name_th
        FROM doctors d
        LEFT JOIN departments dept ON dept.id = d.department_id
        WHERE ($1 = FALSE OR d.is_active = TRUE)
        ORDER BY d.full_name ASC
        """,
        active_only,
    )
    return [dict(r) for r in rows]


@router.post("/doctors", response_model=DoctorOut, status_code=status.HTTP_201_CREATED)
async def create_doctor(
    payload: DoctorCreate,
    connection: asyncpg.Connection = Depends(get_connection),
    admin_user: dict = Depends(require_roles("super_admin", "nurse")),
):
    """Create a new doctor profile. Requires admin or nurse role."""
    row = await connection.fetchrow(
        """
        INSERT INTO doctors (full_name, title, specialization, department_id, phone_ext, notes, is_active, created_by)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING *
        """,
        payload.full_name,
        payload.title,
        payload.specialization,
        payload.department_id,
        payload.phone_ext,
        payload.notes,
        payload.is_active,
        admin_user["id"],
    )
    dept_row = None
    if row["department_id"]:
        dept_row = await connection.fetchrow(
            "SELECT name_en, name_th FROM departments WHERE id = $1", row["department_id"]
        )
    return {**dict(row), "department_name_en": dept_row["name_en"] if dept_row else None,
            "department_name_th": dept_row["name_th"] if dept_row else None}


@router.get("/doctors/{doctor_id}", response_model=DoctorWithSchedulesOut)
async def get_doctor(
    doctor_id: UUID,
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Get a doctor with their full weekly schedule."""
    row = await connection.fetchrow(
        """
        SELECT d.*, dept.name_en AS department_name_en, dept.name_th AS department_name_th
        FROM doctors d
        LEFT JOIN departments dept ON dept.id = d.department_id
        WHERE d.id = $1
        """,
        doctor_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Doctor not found")
    schedules = await connection.fetch(
        "SELECT * FROM doctor_schedules WHERE doctor_id = $1 ORDER BY schedule_date, start_time",
        doctor_id,
    )
    return {**dict(row), "schedules": [dict(s) for s in schedules]}


@router.patch("/doctors/{doctor_id}", response_model=DoctorOut)
async def update_doctor(
    doctor_id: UUID,
    payload: DoctorUpdate,
    connection: asyncpg.Connection = Depends(get_connection),
    _admin_user: dict = Depends(require_roles("super_admin", "nurse")),
):
    """Update a doctor profile. Requires admin or nurse role."""
    existing = await connection.fetchrow("SELECT * FROM doctors WHERE id = $1", doctor_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Doctor not found")
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    set_clauses = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(updates))
    values = list(updates.values())
    row = await connection.fetchrow(
        f"UPDATE doctors SET {set_clauses} WHERE id = $1 RETURNING *",
        doctor_id, *values,
    )
    dept_row = None
    if row["department_id"]:
        dept_row = await connection.fetchrow(
            "SELECT name_en, name_th FROM departments WHERE id = $1", row["department_id"]
        )
    return {**dict(row), "department_name_en": dept_row["name_en"] if dept_row else None,
            "department_name_th": dept_row["name_th"] if dept_row else None}


@router.get("/doctors/{doctor_id}/schedules", response_model=list[DoctorScheduleOut])
async def list_doctor_schedules(
    doctor_id: UUID,
    from_date: str | None = None,
    connection: asyncpg.Connection = Depends(get_connection),
):
    """List schedule entries for a doctor, optionally from a start date."""
    from datetime import date as date_type
    parsed_from: date_type | None = None
    if from_date:
        try:
            parsed_from = date_type.fromisoformat(from_date)
        except ValueError:
            pass
    rows = await connection.fetch(
        """
        SELECT * FROM doctor_schedules
        WHERE doctor_id = $1
          AND ($2::date IS NULL OR schedule_date >= $2)
        ORDER BY schedule_date, start_time
        """,
        doctor_id,
        parsed_from,
    )
    return [dict(r) for r in rows]


@router.post(
    "/doctors/{doctor_id}/schedules",
    response_model=DoctorScheduleOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_doctor_schedule(
    doctor_id: UUID,
    payload: DoctorScheduleCreate,
    connection: asyncpg.Connection = Depends(get_connection),
    _admin_user: dict = Depends(require_roles("super_admin", "nurse")),
):
    """Add a date-specific schedule entry for a doctor."""
    doctor = await connection.fetchrow("SELECT id FROM doctors WHERE id = $1", doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    try:
        row = await connection.fetchrow(
            """
            INSERT INTO doctor_schedules
                (doctor_id, schedule_date, start_time, end_time,
                 break_start, break_end, room, slot_label, is_available, notes)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (doctor_id, schedule_date, start_time)
            DO UPDATE SET
                end_time     = EXCLUDED.end_time,
                break_start  = EXCLUDED.break_start,
                break_end    = EXCLUDED.break_end,
                room         = EXCLUDED.room,
                slot_label   = EXCLUDED.slot_label,
                is_available = EXCLUDED.is_available,
                notes        = EXCLUDED.notes,
                updated_at   = NOW()
            RETURNING *
            """,
            doctor_id,
            payload.schedule_date,
            payload.start_time,
            payload.end_time,
            payload.break_start,
            payload.break_end,
            payload.room,
            payload.slot_label,
            payload.is_available,
            payload.notes,
        )
    except asyncpg.CheckViolationError as exc:
        raise HTTPException(status_code=400, detail="end_time must be after start_time") from exc
    return dict(row)


@router.patch("/doctors/{doctor_id}/schedules/{schedule_id}", response_model=DoctorScheduleOut)
async def update_doctor_schedule(
    doctor_id: UUID,
    schedule_id: UUID,
    payload: DoctorScheduleCreate,
    connection: asyncpg.Connection = Depends(get_connection),
    _admin_user: dict = Depends(require_roles("super_admin", "nurse")),
):
    """Update an existing schedule entry."""
    row = await connection.fetchrow(
        "SELECT id FROM doctor_schedules WHERE id = $1 AND doctor_id = $2",
        schedule_id, doctor_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Schedule entry not found")
    updated = await connection.fetchrow(
        """
        UPDATE doctor_schedules
        SET schedule_date=$2, start_time=$3, end_time=$4,
            break_start=$5, break_end=$6, room=$7,
            slot_label=$8, is_available=$9, notes=$10
        WHERE id = $1
        RETURNING *
        """,
        schedule_id,
        payload.schedule_date,
        payload.start_time,
        payload.end_time,
        payload.break_start,
        payload.break_end,
        payload.room,
        payload.slot_label,
        payload.is_available,
        payload.notes,
    )
    return dict(updated)


@router.delete("/doctors/{doctor_id}/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_doctor_schedule(
    doctor_id: UUID,
    schedule_id: UUID,
    connection: asyncpg.Connection = Depends(get_connection),
    _admin_user: dict = Depends(require_roles("super_admin", "nurse")),
):
    """Delete a schedule entry."""
    result = await connection.execute(
        "DELETE FROM doctor_schedules WHERE id = $1 AND doctor_id = $2",
        schedule_id, doctor_id,
    )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Schedule entry not found")


@router.get("/schedules/available", response_model=list[DoctorWithSchedulesOut])
async def get_available_doctors(
    schedule_date: str | None = None,
    department_id: UUID | None = None,
    connection: asyncpg.Connection = Depends(get_connection),
):
    """
    Return doctors with their available schedule entries for a given date
    (defaults to today). Old entries are never deleted — only today's are surfaced.
    Used by the AI to answer patient availability queries.
    """
    from datetime import date as date_type
    if schedule_date:
        try:
            target_date = date_type.fromisoformat(schedule_date)
        except ValueError:
            target_date = date_type.today()
    else:
        target_date = date_type.today()

    rows = await connection.fetch(
        """
        SELECT d.*, dept.name_en AS department_name_en, dept.name_th AS department_name_th
        FROM doctors d
        LEFT JOIN departments dept ON dept.id = d.department_id
        WHERE d.is_active = TRUE
          AND ($1::uuid IS NULL OR d.department_id = $1)
          AND EXISTS (
              SELECT 1 FROM doctor_schedules s
              WHERE s.doctor_id = d.id
                AND s.schedule_date = $2
                AND s.is_available = TRUE
          )
        ORDER BY d.full_name ASC
        """,
        department_id,
        target_date,
    )
    result = []
    for doctor in rows:
        schedules = await connection.fetch(
            """
            SELECT * FROM doctor_schedules
            WHERE doctor_id = $1 AND schedule_date = $2 AND is_available = TRUE
            ORDER BY start_time
            """,
            doctor["id"],
            target_date,
        )
        result.append({**dict(doctor), "schedules": [dict(s) for s in schedules]})
    return result


# ── Disease Surveillance ──────────────────────────────────────────────────────


# ── Screening reference data ──────────────────────────────────────────────────

@router.get("/screening/vital-bounds")
async def get_vital_bounds(connection: asyncpg.Connection = Depends(get_connection)):
    """Physiologically possible ranges from the active criteria version.

    The kiosk reads these so the patient gets instant, correctly-worded
    feedback instead of a bare 422 — and so the numbers live in exactly one
    place (the criteria document) rather than being retyped in the client.
    """
    from app.services.screening.rules.criteria_store import get_active_criteria

    _, criteria = await get_active_criteria(connection)
    return {
        "bounds": {
            name: bound.model_dump() for name, bound in criteria.vital_bounds.items()
        },
        "cross_checks": {
            check_id: check.model_dump()
            for check_id, check in criteria.cross_checks.items()
        },
    }
