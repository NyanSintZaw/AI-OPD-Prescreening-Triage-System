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

from .database import connect, seed_from_csv

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
    complaint: str | None = None
    vitals: dict[str, Any] | None = None
    reasons: list[str] = Field(default_factory=list)


class RoutingIn(BaseModel):
    department: str
    complaint: str | None = None
    confirmed_by: str
    rerouted: bool = False


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
        source = os.environ.get("HIS_MOCK_DATA_PATH", "") or str(SAMPLE_CSV)
        if Path(source).exists():
            count = seed_from_csv(conn, source)
            print(f"[his-mock] seeded {count} visits from {source}")
    app.state.db = conn

    def get_db(request: Request) -> sqlite3.Connection:
        return request.app.state.db

    def visit_payload(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "visit_id": row["visit_id"],
            "hn": row["hn"],
            "appointment": bool(row["appointment"]),
            "birthdate": row["birthdate"],
            "vitals": {
                "weight": row["weight"],
                "height": row["height"],
                "bmi": row["bmi"],
                "systolic": row["systolic"],
                "diastolic": row["diastolic"],
                "temperature": row["temperature"],
                "pulse": row["pulse"],
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
            "vitals": json.loads(row["vitals"]) if row["vitals"] else None,
            "reasons": json.loads(row["reasons"]) if row["reasons"] else [],
            "status": row["status"],
            "confirmed_department": row["confirmed_department"],
            "confirmed_by": row["confirmed_by"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
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
        """Stage 1 write-back: the AI booth's pending prescreen result.

        Mirrors what the nurse screening station does today: stamps the
        booth as first_location and records the chief complaint, leaving
        second_location for the confirmation step.
        """
        fetch_visit(db, visit_id)
        db.execute(
            """
            INSERT INTO prescreen_results
                (visit_id, session_ref, slip_code, recommended_department,
                 complaint, vitals, reasons, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
            ON CONFLICT(visit_id) DO UPDATE SET
                session_ref = excluded.session_ref,
                slip_code = excluded.slip_code,
                recommended_department = excluded.recommended_department,
                complaint = excluded.complaint,
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
                json.dumps(payload.vitals) if payload.vitals is not None else None,
                json.dumps(payload.reasons),
            ),
        )
        db.execute(
            """
            UPDATE visits SET
                first_location_id = ?, first_location_name = ?,
                first_location_department = ?,
                nurse_chief_complaint = COALESCE(?, nurse_chief_complaint)
            WHERE visit_id = ?
            """,
            (
                AI_BOOTH_LOCATION["id"],
                AI_BOOTH_LOCATION["name"],
                AI_BOOTH_LOCATION["department"],
                payload.complaint,
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
        """Stage 2 write-back: nurse confirmation (or reroute) at the
        destination department. Updates the visit's second_location and
        finalizes the prescreen record."""
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
                complaint = COALESCE(?, complaint),
                updated_at = datetime('now')
            WHERE visit_id = ?
            """,
            (
                "rerouted" if payload.rerouted else "confirmed",
                payload.department,
                payload.confirmed_by,
                payload.complaint,
                visit_id,
            ),
        )
        db.execute(
            """
            UPDATE visits SET
                second_location_id = ?, second_location_name = ?,
                second_location_department = ?,
                nurse_chief_complaint = COALESCE(?, nurse_chief_complaint)
            WHERE visit_id = ?
            """,
            (
                None,
                payload.department,
                payload.department,
                payload.complaint,
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
