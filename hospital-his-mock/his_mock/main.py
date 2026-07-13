"""Mock hospital HIS REST API.

Run (from hospital-his-mock/):

    uv run uvicorn his_mock.main:app --port 8001

Environment:
    HIS_MOCK_DB_PATH    SQLite file (default ./his_mock.db)
    HIS_MOCK_DATA_PATH  hospital CSV export to seed from when the DB is
                        empty (kept OUT of git); falls back to the
                        committed synthetic sample_visits.csv
    HIS_MOCK_API_KEY    required in the X-API-Key header (default demo-his-key)
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .database import connect, parse_pressure, seed_from_csv

PACKAGE_DIR = Path(__file__).resolve().parent
SAMPLE_CSV = PACKAGE_DIR.parent / "sample_visits.csv"

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


class RoutingIn(BaseModel):
    department: str
    complaint: str | None = None
    confirmed_by: str
    rerouted: bool = False


class ResetIn(BaseModel):
    # When empty/omitted, every visit is reset to its pre-registration state.
    visit_ids: list[str] = Field(default_factory=list)


# Every screening column our system writes back; a reset NULLs these, leaving
# only the pre-registration fields (visit_id / hnx / birthdate / appointment)
# so the visit returns to the "registered" state the demo starts from.
_RESET_COLUMNS = (
    "measure_spid", "measure_name", "measure_department", "modify_time",
    "weight", "height", "bmi", "waist_width", "pressure", "temperature", "pulse",
    "nurse_chief_complaint", "nurse_patient_illness",
    "first_location_id", "first_location_name", "first_location_department",
    "second_location_id", "second_location_name", "second_location_department",
)
_RESET_SET_CLAUSE = ", ".join(f"{col} = NULL" for col in _RESET_COLUMNS)


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


def _api_key() -> str:
    return os.environ.get("HIS_MOCK_API_KEY", "demo-his-key")


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if x_api_key != _api_key():
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


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
    app.state.db = conn

    def get_db(request: Request) -> sqlite3.Connection:
        return request.app.state.db

    def _screening_status(row: sqlite3.Row) -> str:
        """registered → screened → routed, from which fields are filled."""
        if row["second_location_department"]:
            return "routed"
        if row["first_location_department"]:
            return "screened"
        return "registered"

    def visit_payload(row: sqlite3.Row) -> dict[str, Any]:
        systolic, diastolic = parse_pressure(row["pressure"])
        return {
            "visit_id": row["visit_id"],
            "hnx": row["hnx"],
            "appointment": bool(row["appointment"]),
            "birthdate": row["birthdate"],
            "screening_status": _screening_status(row),
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
        return visit_payload(fetch_visit(db, visit_id))

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

    @app.put(
        "/api/visits/{visit_id}/routing",
        dependencies=[Depends(require_api_key)],
    )
    def confirm_routing(
        visit_id: str,
        payload: RoutingIn,
        db: sqlite3.Connection = Depends(get_db),
    ):
        """Stage 2 write-back — publish the clinical narrative + routing.

        Human sign-off. Promotes the held complaint summary + reason into the
        nurse_* fields and writes second_location (the confirmed/rerouted
        department) onto the visit row."""
        fetch_visit(db, visit_id)
        existing = db.execute(
            "SELECT * FROM prescreen_results WHERE visit_id = ?", (visit_id,)
        ).fetchone()
        if existing is None:
            raise HTTPException(
                status_code=409, detail="No prescreen result to confirm for this visit"
            )
        db.execute(
            """
            UPDATE prescreen_results SET
                status = ?, confirmed_department = ?, confirmed_by = ?,
                updated_at = datetime('now')
            WHERE visit_id = ?
            """,
            (
                "rerouted" if payload.rerouted else "confirmed",
                payload.department,
                payload.confirmed_by,
                visit_id,
            ),
        )
        # Publish the held clinical narrative. On reroute, the nurse's note
        # (payload.complaint) overrides the AI reason for the illness field.
        chief_complaint = existing["complaint"]
        illness = payload.complaint or existing["reason"]
        db.execute(
            """
            UPDATE visits SET
                nurse_chief_complaint = ?, nurse_patient_illness = ?,
                second_location_id = ?, second_location_name = ?,
                second_location_department = ?,
                modify_time = datetime('now')
            WHERE visit_id = ?
            """,
            (
                chief_complaint,
                illness,
                None,
                payload.department,
                payload.department,
                visit_id,
            ),
        )
        db.commit()
        row = db.execute(
            "SELECT * FROM prescreen_results WHERE visit_id = ?", (visit_id,)
        ).fetchone()
        return prescreen_payload(row)

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
        """
        visit_ids = list(payload.visit_ids) if payload else []
        if visit_ids:
            placeholders = ",".join("?" for _ in visit_ids)
            db.execute(
                f"DELETE FROM prescreen_results WHERE visit_id IN ({placeholders})",
                visit_ids,
            )
            db.execute(
                f"UPDATE visits SET {_RESET_SET_CLAUSE} WHERE visit_id IN ({placeholders})",
                visit_ids,
            )
            affected = visit_ids
        else:
            db.execute("DELETE FROM prescreen_results")
            db.execute(f"UPDATE visits SET {_RESET_SET_CLAUSE}")
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
