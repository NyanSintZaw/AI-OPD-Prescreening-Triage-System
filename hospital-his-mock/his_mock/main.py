"""Mock hospital HIS REST API.

Run (from hospital-his-mock/):

    uv run uvicorn his_mock.main:app --port 8001

Environment:
    HIS_MOCK_DB_PATH             SQLite file (default ./his_mock.db)
    HIS_MOCK_DATA_PATH           hospital visits CSV export to seed from when
                                 the DB is empty (kept OUT of git); falls back
                                 to the committed synthetic sample_visits.csv
    HIS_MOCK_PATIENTS_DATA_PATH  hospital patients (HN) CSV export to seed
                                 from when the DB is empty; falls back to the
                                 committed synthetic sample_patients.csv
    HIS_MOCK_API_KEY             required in the X-API-Key header (default demo-his-key)
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .database import (
    backfill_patients_from_visits,
    connect,
    parse_pressure,
    seed_from_csv,
    seed_patients_from_csv,
    seed_service_points,
)

PACKAGE_DIR = Path(__file__).resolve().parent
SAMPLE_CSV = PACKAGE_DIR.parent / "sample_visits.csv"
SAMPLE_PATIENTS_CSV = PACKAGE_DIR.parent / "sample_patients.csv"

# The station identity the hospital would assign our booth. The department
# string is the hospital's real OPD screening unit from their export.
AI_BOOTH_LOCATION = {
    "id": "AI-BOOTH-01",
    "name": "AI Pre-Screening Booth",
    "department": "แผนก ผู้ป่วยนอก(หน่วยคัดกรอง)",
}


class PrescreenIn(BaseModel):
    session_ref: str
    slip_code: str | None = None
    recommended_department: str
    complaint: str | None = None          # our concise symptoms_summary
    reason: str | None = None             # our routing key_reason
    vitals: dict[str, Any] | None = None
    reasons: list[str] = Field(default_factory=list)


class SbarIn(BaseModel):
    """Clinical handover, all fields optional per the iMed contract."""

    situation: str | None = None
    background: str | None = None
    assessment: str | None = None
    assessment_problem: str | None = None
    assessment_equipment: str | None = None
    recommend: str | None = None
    documentation: str | None = None


class AssignmentIn(BaseModel):
    """Body of POST /api/v1/patient-assignments — mirrors the hospital's iMed
    contract (docs/imed-patient-assignment-api.md).

    We never send patient_id / fix_visit_type_id / any timestamp: iMed derives
    those from the visit and from the access-token identity.
    """

    request_id: str
    visit_id: str
    assign_spid: str
    assign_eid: str | None = None
    base_department_id: str | None = None
    queue_number: str | None = None
    sbar: SbarIn | None = None


class FollowUpIn(BaseModel):
    # Patient's own follow-up question/concern captured at the booth,
    # recorded for the destination doctor/nurse to address.
    follow_up: str


class ResetIn(BaseModel):
    # When empty/omitted, every visit is reset to its pre-registration state.
    visit_ids: list[str] = Field(default_factory=list)
    # Demo repeatability: resetting visits normally leaves patient (HN)
    # history alone, since it's meant to carry across visits. Set this to
    # also wipe the affected patients' history/last-vitals fields back to
    # "first-time patient" so the history-intake flow can be re-demoed.
    reset_history: bool = False


class PatientHistoryIn(BaseModel):
    smoking_alcohol: str | None = None
    allergies: str | None = None
    chronic_conditions: str | None = None
    past_surgeries: str | None = None
    family_history: str | None = None


class PatientVitalsIn(BaseModel):
    # Booth vitals naming, matching PrescreenIn.vitals's weight_kg/height_cm.
    weight_kg: float | None = None
    height_cm: float | None = None


# Every screening column our system writes back; a reset NULLs these, leaving
# only the pre-registration fields (visit_id / hnx / birthdate / appointment)
# so the visit returns to the "registered" state the demo starts from.
_RESET_COLUMNS = (
    "measure_spid", "measure_name", "measure_department", "modify_time",
    "weight", "height", "bmi", "waist_width", "pressure", "temperature", "pulse",
    "nurse_chief_complaint", "nurse_patient_illness", "follow_up",
    "first_location_id", "first_location_name", "first_location_department",
    "second_location_id", "second_location_name", "second_location_department",
    "visit_lock_status",
)
_RESET_SET_CLAUSE = ", ".join(f"{col} = NULL" for col in _RESET_COLUMNS)

# Patient (HN) history/last-vitals columns cleared by ``reset_history=True`` —
# puts a patient back into "first-time" state (``history_recorded_at`` NULL).
_PATIENT_RESET_COLUMNS = (
    "smoking_alcohol", "allergies", "chronic_conditions", "past_surgeries",
    "family_history", "history_recorded_at", "last_weight", "last_height",
    "vitals_measured_at",
)
_PATIENT_RESET_SET_CLAUSE = ", ".join(f"{col} = NULL" for col in _PATIENT_RESET_COLUMNS)


def _vitals_to_columns(vitals: dict[str, Any] | None) -> dict[str, Any]:
    """Map our referral vitals dict to the export's visit columns.

    Booth vitals arrive as ``systolic/diastolic/pulse_bpm/weight_kg/
    height_cm/temperature``; the export stores raw ``pressure`` "sys/dia",
    ``pulse``, ``weight``, ``height``, ``temperature`` and a computed ``bmi``.
    """
    v = vitals or {}
    systolic = v.get("systolic")
    diastolic = v.get("diastolic")
    pressure = f"{systolic}/{diastolic}" if systolic and diastolic else None
    weight = v.get("weight_kg")
    height = v.get("height_cm")
    bmi = None
    try:
        if weight and height:
            bmi = round(float(weight) / (float(height) / 100) ** 2, 2)
    except (TypeError, ValueError, ZeroDivisionError):
        bmi = None
    return {
        "pressure": pressure,
        "pulse": v.get("pulse_bpm"),
        "weight": weight,
        "height": height,
        "temperature": v.get("temperature"),
        "bmi": bmi,
    }


def _queue_result(row: sqlite3.Row) -> dict[str, Any]:
    """The ``result`` object of an assignment response, from a visit_queue row."""
    return {
        "visit_id": row["visit_id"],
        "visit_queue_id": row["visit_queue_id"],
        "assign_spid": row["next_location_spid"],
        "assign_eid": row["next_operate_eid"],
        "queue_number": row["queue_number"],
        "queue_status": row["queue_status"],
        "sbar_id": row["sbar_id"],
    }


def _next_queue_number(db: sqlite3.Connection, sp: sqlite3.Row) -> str:
    """Per-service-point daily sequence, e.g. ``M014``.

    ponytail: naive COUNT+1, races under concurrency. The mock runs on one
    sqlite connection and iMed owns real sequencing/prefixes/daily resets —
    this only has to look plausible in a demo.
    """
    seq = db.execute(
        """
        SELECT COUNT(*) FROM visit_queue
        WHERE next_location_spid = ? AND date(created_at) = date('now')
        """,
        (sp["spid"],),
    ).fetchone()[0]
    return f"{sp['queue_prefix'] or 'A'}{seq + 1:03d}"


def _imed_ok(request_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return {"request_id": request_id, "status": "STATUS_SUCCESS", "result": result}


def _imed_error(
    http_status: int, request_id: str, code: str, message_th: str
) -> JSONResponse:
    """iMed's error envelope is FLAT (status/message/message_th) — nothing like
    FastAPI's ``{"detail": ...}``. Hence JSONResponse instead of raising
    HTTPException, so the shape our adapter parses is the real one."""
    return JSONResponse(
        status_code=http_status,
        content={
            "request_id": request_id,
            "status": "STATUS_BUSINESS_ERROR",
            "message": code,
            "message_th": message_th,
        },
    )


def _api_key() -> str:
    return os.environ.get("HIS_MOCK_API_KEY", "demo-his-key")


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if x_api_key != _api_key():
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


def require_imed_token(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> None:
    """Auth for the iMed-shaped endpoint, which the real contract specifies as
    ``Authorization: Bearer <token>``. Accepts ``X-API-Key`` too so the same
    single credential works against both this mock's older endpoints and the
    real API — matching ``his_auth_headers()`` on our side, which sends both.
    """
    expected = _api_key()
    bearer = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()
    if bearer == expected or x_api_key == expected:
        return
    raise HTTPException(
        status_code=401, detail="Invalid or missing Authorization / X-API-Key"
    )


def build_app(db_path: str | Path | None = None) -> FastAPI:
    app = FastAPI(
        title="Hospital HIS (mock)",
        description=(
            "Simulates the hospital's visit database behind a REST API. "
            "The data in here belongs to the 'hospital side' of the demo — "
            "the triage system can only reach it through these endpoints."
        ),
    )

    resolved_db = Path(db_path or os.environ.get("HIS_MOCK_DB_PATH", "his_mock.db"))
    conn = connect(resolved_db)
    if conn.execute("SELECT COUNT(*) FROM visits").fetchone()[0] == 0:
        # A real export (HIS_MOCK_DATA_PATH) loads complete rows; the bundled
        # synthetic sample loads in pre-registration state (screening fields
        # blank) so the demo shows our system filling them in.
        real_source = os.environ.get("HIS_MOCK_DATA_PATH", "")
        source = real_source or str(SAMPLE_CSV)
        if Path(source).exists():
            count = seed_from_csv(
                conn, source, pre_registration_only=not real_source
            )
            print(f"[his-mock] seeded {count} visits from {source}")
    if conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0] == 0:
        patients_source = (
            os.environ.get("HIS_MOCK_PATIENTS_DATA_PATH", "") or str(SAMPLE_PATIENTS_CSV)
        )
        if Path(patients_source).exists():
            count = seed_patients_from_csv(conn, patients_source)
            print(f"[his-mock] seeded {count} patients from {patients_source}")
    # Any visit whose hnx has no patient row yet (e.g. a real export whose
    # HNs aren't in the patients CSV) gets a bare, first-time record.
    backfill_patients_from_visits(conn)
    seed_service_points(conn)
    app.state.db = conn

    @app.exception_handler(RequestValidationError)
    async def _validation_to_imed_error(request: Request, exc: RequestValidationError):
        """A malformed assignment body must be 400 ``invalid_request``, not
        FastAPI's default 422 — our adapter maps 422 to "service point closed",
        so the default would tell the nurse a lie about why it failed."""
        if request.url.path.startswith("/api/v1/"):
            body = getattr(exc, "body", None)
            rid = body.get("request_id", "") if isinstance(body, dict) else ""
            return _imed_error(
                400, rid or "", "invalid_request", "ข้อมูลไม่ครบหรือไม่ถูกต้อง"
            )
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    def get_db(request: Request) -> sqlite3.Connection:
        return request.app.state.db

    def _screening_status(row: sqlite3.Row) -> str:
        """registered → screened → routed, from which fields are filled."""
        if row["second_location_department"]:
            return "routed"
        if row["first_location_department"]:
            return "screened"
        return "registered"

    def fetch_patient(db: sqlite3.Connection, hn: str) -> sqlite3.Row | None:
        return db.execute("SELECT * FROM patients WHERE hn = ?", (hn,)).fetchone()

    def patient_payload(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "hn": row["hn"],
            "patient_name": row["patient_name"],
            "birthdate": row["birthdate"],
            # A patient with no recorded history yet is first-time — the
            # booth should collect it before the symptom interview.
            "is_first_time": row["history_recorded_at"] is None,
            "history": {
                "smoking_alcohol": row["smoking_alcohol"],
                "allergies": row["allergies"],
                "chronic_conditions": row["chronic_conditions"],
                "past_surgeries": row["past_surgeries"],
                "family_history": row["family_history"],
                "recorded_at": row["history_recorded_at"],
            },
            "last_vitals": {
                "weight": row["last_weight"],
                "height": row["last_height"],
                "measured_at": row["vitals_measured_at"],
            },
        }

    def visit_payload(row: sqlite3.Row, db: sqlite3.Connection) -> dict[str, Any]:
        systolic, diastolic = parse_pressure(row["pressure"])
        patient_row = fetch_patient(db, row["hnx"]) if row["hnx"] else None
        return {
            "visit_id": row["visit_id"],
            "hnx": row["hnx"],
            # Alias of ``hnx`` under the field name a real hospital HIS
            # export may use (see docs/his-integration.md §6.1) — read
            # either from the app side.
            "hn": row["hnx"],
            "patient_name": row["patient_name"],
            "appointment": bool(row["appointment"]),
            "birthdate": row["birthdate"],
            "screening_status": _screening_status(row),
            # HN master record (history + last-known vitals) so a single
            # GET gives the triage app everything it needs in one round
            # trip; null when the HN is entirely unknown (shouldn't happen
            # once backfill_patients_from_visits has run).
            "patient": patient_payload(patient_row) if patient_row else None,
            # Vitals as the export carries them (raw pressure) plus a parsed
            # split for convenience.
            "vitals": {
                "weight": row["weight"],
                "height": row["height"],
                "bmi": row["bmi"],
                "waist_width": row["waist_width"],
                "pressure": row["pressure"],
                "systolic": systolic,
                "diastolic": diastolic,
                "temperature": row["temperature"],
                "pulse": row["pulse"],
            },
            "measure": {
                "spid": row["measure_spid"],
                "name": row["measure_name"],
                "department": row["measure_department"],
            },
            "nurse_chief_complaint": row["nurse_chief_complaint"],
            "nurse_patient_illness": row["nurse_patient_illness"],
            "follow_up": row["follow_up"],
            "first_location": {
                "id": row["first_location_id"],
                "name": row["first_location_name"],
                "department": row["first_location_department"],
            },
            "second_location": {
                "id": row["second_location_id"],
                "name": row["second_location_name"],
                "department": row["second_location_department"],
            },
            "modify_time": row["modify_time"],
        }

    def fetch_visit(db: sqlite3.Connection, visit_id: str) -> sqlite3.Row:
        row = db.execute(
            "SELECT * FROM visits WHERE visit_id = ?", (visit_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Visit not found")
        return row

    def prescreen_payload(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "visit_id": row["visit_id"],
            "session_ref": row["session_ref"],
            "slip_code": row["slip_code"],
            "recommended_department": row["recommended_department"],
            "complaint": row["complaint"],
            "reason": row["reason"],
            "vitals": json.loads(row["vitals"]) if row["vitals"] else None,
            "reasons": json.loads(row["reasons"]) if row["reasons"] else [],
            "status": row["status"],
            "confirmed_department": row["confirmed_department"],
            "confirmed_by": row["confirmed_by"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @app.get("/api/visits", dependencies=[Depends(require_api_key)])
    def list_visits(db: sqlite3.Connection = Depends(get_db)):
        """List all visits with their before/after screening status — powers
        the admin dashboard's 'Hospital DB' view."""
        rows = db.execute(
            "SELECT * FROM visits ORDER BY visit_id"
        ).fetchall()
        return {
            "visits": [
                {
                    "visit_id": r["visit_id"],
                    "hnx": r["hnx"],
                    "patient_name": r["patient_name"],
                    "appointment": bool(r["appointment"]),
                    "birthdate": r["birthdate"],
                    "screening_status": _screening_status(r),
                    "modify_time": r["modify_time"],
                }
                for r in rows
            ]
        }

    @app.get("/api/visits/{visit_id}", dependencies=[Depends(require_api_key)])
    def get_visit(visit_id: str, db: sqlite3.Connection = Depends(get_db)):
        return visit_payload(fetch_visit(db, visit_id), db)

    @app.post(
        "/api/visits/{visit_id}/prescreen",
        status_code=201,
        dependencies=[Depends(require_api_key)],
    )
    def push_prescreen(
        visit_id: str,
        payload: PrescreenIn,
        db: sqlite3.Connection = Depends(get_db),
    ):
        """Stage 1 write-back — objective booth data only.

        Writes the measurements taken at our booth + the booth as
        first_location/measure onto the visit row. The clinical narrative
        (complaint summary, reason) and the recommended department are HELD
        in prescreen_results (pending) and NOT published to the visit row
        until a nurse confirms at the destination (Stage 2).
        """
        fetch_visit(db, visit_id)
        db.execute(
            """
            INSERT INTO prescreen_results
                (visit_id, session_ref, slip_code, recommended_department,
                 complaint, reason, vitals, reasons, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            ON CONFLICT(visit_id) DO UPDATE SET
                session_ref = excluded.session_ref,
                slip_code = excluded.slip_code,
                recommended_department = excluded.recommended_department,
                complaint = excluded.complaint,
                reason = excluded.reason,
                vitals = excluded.vitals,
                reasons = excluded.reasons,
                status = 'pending',
                confirmed_department = NULL,
                confirmed_by = NULL,
                updated_at = datetime('now')
            """,
            (
                visit_id,
                payload.session_ref,
                payload.slip_code,
                payload.recommended_department,
                payload.complaint,
                payload.reason,
                json.dumps(payload.vitals) if payload.vitals is not None else None,
                json.dumps(payload.reasons),
            ),
        )
        cols = _vitals_to_columns(payload.vitals)
        db.execute(
            """
            UPDATE visits SET
                measure_spid = ?, measure_name = ?, measure_department = ?,
                first_location_id = ?, first_location_name = ?,
                first_location_department = ?,
                pressure = ?, pulse = ?, weight = ?, height = ?,
                temperature = ?, bmi = ?,
                modify_time = datetime('now')
            WHERE visit_id = ?
            """,
            (
                AI_BOOTH_LOCATION["id"], AI_BOOTH_LOCATION["name"],
                AI_BOOTH_LOCATION["department"],
                AI_BOOTH_LOCATION["id"], AI_BOOTH_LOCATION["name"],
                AI_BOOTH_LOCATION["department"],
                cols["pressure"], cols["pulse"], cols["weight"], cols["height"],
                cols["temperature"], cols["bmi"],
                visit_id,
            ),
        )
        db.commit()
        row = db.execute(
            "SELECT * FROM prescreen_results WHERE visit_id = ?", (visit_id,)
        ).fetchone()
        return prescreen_payload(row)

    @app.post(
        "/api/v1/patient-assignments",
        dependencies=[Depends(require_imed_token)],
    )
    def create_patient_assignment(
        payload: AssignmentIn,
        db: sqlite3.Connection = Depends(get_db),
    ):
        """Send a registered visit to a destination service point.

        Mirrors the hospital's real iMed contract
        (``docs/imed-patient-assignment-api.md``) — same envelope, same error
        codes, same idempotency rule. Replaces the retired
        ``PUT /api/visits/{id}/routing``.

        Two deliberate divergences, both flagged for the hospital meeting:

        * A repeated ``request_id`` returns **200 with the original result**
          rather than a bare 409. That is our *change request 7* — an
          idempotency key is useless if a retry after a timeout cannot tell us
          the queue number. Implemented here so the proposal is runnable.
        * ``confirmed_by`` is left NULL and a reroute cannot be marked as such:
          iMed derives the sender from the access token and has no reroute
          flag (change requests 3 and 4). The empty column is the demo.
        """
        rid = payload.request_id
        visit = db.execute(
            "SELECT * FROM visits WHERE visit_id = ?", (payload.visit_id,)
        ).fetchone()
        if visit is None:
            # The contract lists no 404 for this endpoint; an unknown visit is
            # bad data from the third party.
            return _imed_error(400, rid, "invalid_request", "ไม่พบ visit ที่ระบุ")

        # Idempotent replay, checked BEFORE the lock/service-point gates so a
        # retry still yields the queue number even if the SP has since closed.
        prior = db.execute(
            "SELECT * FROM visit_queue WHERE request_id = ?", (rid,)
        ).fetchone()
        if prior is not None:
            return _imed_ok(rid, _queue_result(prior))

        if visit["visit_lock_status"] in ("LOCKED", "FINANCIAL_DISCHARGE"):
            return _imed_error(
                403,
                rid,
                "VISIT_LOCKED_OR_FINANCIAL_DISCHARGED",
                "visit ถูกล็อกหรือจำหน่ายทางการเงินแล้ว",
            )

        sp = db.execute(
            "SELECT * FROM service_points WHERE spid = ?", (payload.assign_spid,)
        ).fetchone()
        if sp is None:
            return _imed_error(
                400, rid, "invalid_request", "ไม่รู้จักจุดบริการปลายทางที่ระบุ"
            )
        if not sp["is_open"]:
            return _imed_error(
                422,
                rid,
                "SERVICE_POINT_NOT_AVAILABLE",
                "จุดบริการปลายทางไม่พร้อมให้บริการ",
            )

        duplicate = db.execute(
            """
            SELECT 1 FROM visit_queue
            WHERE visit_id = ? AND next_location_spid = ?
              AND queue_status IN ('WAITING', 'NOT_SEND')
            """,
            (payload.visit_id, payload.assign_spid),
        ).fetchone()
        if duplicate is not None:
            return _imed_error(
                409,
                rid,
                "VISIT_QUEUE_ALREADY_EXIST",
                "ผู้ป่วยอยู่ในคิวของจุดบริการปลายทางแล้ว",
            )

        # iMed clears the visit's previous queue when assigning. CANCELLED
        # rather than deleted, so a reroute stays legible in the demo.
        db.execute(
            """
            UPDATE visit_queue SET queue_status = 'CANCELLED'
            WHERE visit_id = ? AND queue_status IN ('WAITING', 'NOT_SEND')
            """,
            (payload.visit_id,),
        )

        queue_number = payload.queue_number or _next_queue_number(db, sp)
        visit_queue_id = f"VQ-{uuid.uuid4().hex[:10].upper()}"
        sbar = payload.sbar.model_dump() if payload.sbar else None
        sbar_id = f"SBAR-{uuid.uuid4().hex[:6].upper()}" if sbar else None
        db.execute(
            """
            INSERT INTO visit_queue (
                visit_queue_id, request_id, visit_id, next_location_spid,
                next_department_id, next_operate_eid, queue_number,
                queue_status, sbar, sbar_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'WAITING', ?, ?)
            """,
            (
                visit_queue_id,
                rid,
                payload.visit_id,
                payload.assign_spid,
                payload.base_department_id or sp["department_id"],
                payload.assign_eid,
                queue_number,
                json.dumps(sbar, ensure_ascii=False) if sbar else None,
                sbar_id,
            ),
        )

        # Publish onto the visit row. second_location_id finally carries the
        # real service-point id — the retired routing endpoint hardcoded None.
        chief_complaint = (sbar or {}).get("situation")
        illness = (sbar or {}).get("assessment_problem")
        db.execute(
            """
            UPDATE visits SET
                second_location_id = ?, second_location_name = ?,
                second_location_department = ?,
                nurse_chief_complaint = COALESCE(?, nurse_chief_complaint),
                nurse_patient_illness = COALESCE(?, nurse_patient_illness),
                modify_time = datetime('now')
            WHERE visit_id = ?
            """,
            (
                sp["spid"],
                sp["name"],
                sp["name"],
                chief_complaint,
                illness,
                payload.visit_id,
            ),
        )
        # Our own staging row, when there is one. An assignment must NOT depend
        # on it: iMed has no concept of our Stage 1 pre-screen.
        db.execute(
            """
            UPDATE prescreen_results SET
                status = 'confirmed', confirmed_department = ?,
                updated_at = datetime('now')
            WHERE visit_id = ?
            """,
            (sp["name"], payload.visit_id),
        )
        db.commit()

        row = db.execute(
            "SELECT * FROM visit_queue WHERE visit_queue_id = ?", (visit_queue_id,)
        ).fetchone()
        return _imed_ok(rid, _queue_result(row))

    @app.put(
        "/api/visits/{visit_id}/follow-up",
        dependencies=[Depends(require_api_key)],
    )
    def update_follow_up(
        visit_id: str,
        payload: FollowUpIn,
        db: sqlite3.Connection = Depends(get_db),
    ):
        """Record the patient's own follow-up question/concern from the booth.

        Written as soon as the patient states it (end of the booth flow) —
        unlike the nurse narrative it needs no human sign-off, it IS the
        patient's verbatim words for the doctor."""
        fetch_visit(db, visit_id)
        db.execute(
            """
            UPDATE visits SET follow_up = ?, modify_time = datetime('now')
            WHERE visit_id = ?
            """,
            (payload.follow_up.strip() or None, visit_id),
        )
        db.commit()
        return visit_payload(fetch_visit(db, visit_id), db)

    @app.get(
        "/api/visits/{visit_id}/prescreen",
        dependencies=[Depends(require_api_key)],
    )
    def get_prescreen(visit_id: str, db: sqlite3.Connection = Depends(get_db)):
        row = db.execute(
            "SELECT * FROM prescreen_results WHERE visit_id = ?", (visit_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="No prescreen result")
        return prescreen_payload(row)

    @app.get("/api/patients", dependencies=[Depends(require_api_key)])
    def list_patients(db: sqlite3.Connection = Depends(get_db)):
        """List all HN master records with their visit counts — powers the
        admin dashboard's 'Hospital DB' HN tab."""
        rows = db.execute("SELECT * FROM patients ORDER BY hn").fetchall()
        counts = dict(
            db.execute(
                "SELECT hnx, COUNT(*) FROM visits WHERE hnx IS NOT NULL GROUP BY hnx"
            ).fetchall()
        )
        return {
            "patients": [
                {**patient_payload(r), "visit_count": counts.get(r["hn"], 0)}
                for r in rows
            ]
        }

    @app.get("/api/patients/{hn}", dependencies=[Depends(require_api_key)])
    def get_patient(hn: str, db: sqlite3.Connection = Depends(get_db)):
        """HN master record: demographics + history + last-known vitals.

        ``is_first_time`` is ``true`` iff ``history_recorded_at`` is NULL —
        the signal the booth uses to decide whether to run the first-time
        patient history intake.
        """
        row = fetch_patient(db, hn)
        if row is None:
            raise HTTPException(status_code=404, detail="Patient not found")
        return patient_payload(row)

    @app.put(
        "/api/patients/{hn}/history",
        dependencies=[Depends(require_api_key)],
    )
    def update_patient_history(
        hn: str,
        payload: PatientHistoryIn,
        db: sqlite3.Connection = Depends(get_db),
    ):
        """Record first-time-patient history collected at the booth.

        Upserts the full history (no partial-field merge, matching this
        service's other write-back endpoints) and stamps
        ``history_recorded_at`` — from this point on the patient is no
        longer first-time, on this visit and any future one."""
        if fetch_patient(db, hn) is None:
            raise HTTPException(status_code=404, detail="Patient not found")
        db.execute(
            """
            UPDATE patients SET
                smoking_alcohol = ?, allergies = ?, chronic_conditions = ?,
                past_surgeries = ?, family_history = ?,
                history_recorded_at = datetime('now')
            WHERE hn = ?
            """,
            (
                payload.smoking_alcohol,
                payload.allergies,
                payload.chronic_conditions,
                payload.past_surgeries,
                payload.family_history,
                hn,
            ),
        )
        db.commit()
        return patient_payload(fetch_patient(db, hn))

    @app.put(
        "/api/patients/{hn}/vitals",
        dependencies=[Depends(require_api_key)],
    )
    def update_patient_vitals(
        hn: str,
        payload: PatientVitalsIn,
        db: sqlite3.Connection = Depends(get_db),
    ):
        """Record the most recent booth weight/height for this HN, so a
        future visit's booth can decide to skip re-asking within the
        recency window."""
        if fetch_patient(db, hn) is None:
            raise HTTPException(status_code=404, detail="Patient not found")
        db.execute(
            """
            UPDATE patients SET
                last_weight = ?, last_height = ?, vitals_measured_at = datetime('now')
            WHERE hn = ?
            """,
            (payload.weight_kg, payload.height_cm, hn),
        )
        db.commit()
        return patient_payload(fetch_patient(db, hn))

    @app.post("/api/admin/reset", dependencies=[Depends(require_api_key)])
    def reset_visits(
        payload: ResetIn | None = None,
        db: sqlite3.Connection = Depends(get_db),
    ):
        """Testing convenience: return visits to their pre-registration
        ("registered") state so a demo can be re-run against the same visit
        IDs. Clears the held prescreen results and NULLs every screening
        column our system writes back (booth measurements, first/second
        location, nurse narrative). Pre-registration fields
        (visit_id / hnx / birthdate / appointment) are untouched.

        With ``visit_ids`` it resets only those; otherwise it resets every
        visit. Note: against a completed real export (``HIS_MOCK_DATA_PATH``)
        this also clears the export's screening fields — it is a demo/test tool.

        Patient (HN) history is left alone by default, since it's meant to
        carry across visits — pass ``reset_history: true`` to also wipe the
        affected patients' history/last-vitals back to "first-time" so that
        flow can be re-demoed against the same synthetic HNs.
        """
        visit_ids = list(payload.visit_ids) if payload else []
        reset_history = bool(payload and payload.reset_history)
        if visit_ids:
            placeholders = ",".join("?" for _ in visit_ids)
            db.execute(
                f"DELETE FROM prescreen_results WHERE visit_id IN ({placeholders})",
                visit_ids,
            )
            if reset_history:
                hns = [
                    r["hnx"]
                    for r in db.execute(
                        f"SELECT DISTINCT hnx FROM visits WHERE visit_id IN ({placeholders})",
                        visit_ids,
                    )
                    if r["hnx"]
                ]
                if hns:
                    hn_placeholders = ",".join("?" for _ in hns)
                    db.execute(
                        f"UPDATE patients SET {_PATIENT_RESET_SET_CLAUSE} "
                        f"WHERE hn IN ({hn_placeholders})",
                        hns,
                    )
            db.execute(
                f"UPDATE visits SET {_RESET_SET_CLAUSE} WHERE visit_id IN ({placeholders})",
                visit_ids,
            )
            # Without this a second demo run of the same visit lands on the
            # 409 duplicate-queue path and looks like a bug on stage.
            db.execute(
                f"DELETE FROM visit_queue WHERE visit_id IN ({placeholders})",
                visit_ids,
            )
            affected = visit_ids
        else:
            db.execute("DELETE FROM prescreen_results")
            if reset_history:
                db.execute(f"UPDATE patients SET {_PATIENT_RESET_SET_CLAUSE}")
            db.execute(f"UPDATE visits SET {_RESET_SET_CLAUSE}")
            db.execute("DELETE FROM visit_queue")
            affected = [r["visit_id"] for r in db.execute("SELECT visit_id FROM visits")]
        db.commit()
        return {"reset": len(affected), "visit_ids": affected}

    @app.get("/api/departments", dependencies=[Depends(require_api_key)])
    def list_departments(db: sqlite3.Connection = Depends(get_db)):
        rows = db.execute(
            """
            SELECT DISTINCT department FROM (
                SELECT first_location_department AS department FROM visits
                UNION
                SELECT second_location_department FROM visits
            ) WHERE department IS NOT NULL
            ORDER BY department
            """
        ).fetchall()
        return {"departments": [r["department"] for r in rows]}

    return app


app = build_app()
