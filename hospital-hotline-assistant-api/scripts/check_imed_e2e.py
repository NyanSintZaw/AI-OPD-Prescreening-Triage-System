"""End-to-end check of the iMed patient-assignment path.

Proves the whole chain actually joins up:

    booth session → link patient (HN) → (disposition) → nurse SBAR preview →
    nurse edits + approves → hospital assignment (department-level) →
    queue number → hospital visit row updated → re-approve is idempotent

This is the join nothing else covers: the adapter has unit tests, the mock has
its own suite, but until now nothing exercised `_push_his_routing` or proved a
queue number reaches the nurse.

**No Google credentials and no LLM.** The screening turn itself is not the
thing under test, so the disposed state is seeded straight into Postgres
exactly as ``TriageService`` would leave it.

Prerequisites (same as the other scripts/check_*.py):
    * Postgres up + migrated       (docker compose up -d && scripts/init_db.py)
    * Mock HIS on :8001            (docker compose, or uvicorn his_mock.main:app)
    * Backend on :8000 with HIS_MODE=http, HIS_BASE_URL=http://localhost:8001

Usage (from hospital-hotline-assistant-api/):

    uv run python scripts/check_imed_e2e.py

Exits non-zero on the first failed assertion.
"""

import asyncio
import json
import os
import sys
import uuid

import asyncpg
import httpx

API = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
HIS = os.getenv("HIS_BASE_URL", "http://localhost:8001").rstrip("/")
HIS_KEY = os.getenv("HIS_API_KEY", "demo-his-key")
DB = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/hospital_hotline"
)
HN = os.getenv("E2E_HN", "09900001")
EMAIL = os.getenv("E2E_EMAIL", "opd.nurse@mfu.local")
PASSWORD = os.getenv("E2E_PASSWORD", "nurse1234")

# Level 3 / internal medicine, with a cited Thai reason — what the engine
# produces for a chest-pain-with-risk-factors case.
CLASSIFICATION = {
    "classified": True,
    "level": 3,
    "color": "yellow",
    "label": "Urgent",
    "department_code": "opd_internal_medicine",
    "response_time": "30 นาที",
    "symptoms_summary": "แน่นหน้าอกมา 2 ชั่วโมง ร้าวไปแขนซ้าย",
    "key_reason": "Chest pain with cardiac risk factors",
    "pain_score": 6,
    "red_flags": [],
    "disposition_reasons": [
        {
            "rule_id": "cp_risk_factors",
            "text_en": "Chest pain with cardiac risk factors",
            "text_th": "เจ็บหน้าอกร่วมกับปัจจัยเสี่ยงโรคหัวใจ",
            "citation": "คู่มือคัดกรอง MFU ข้อ 4.2",
        }
    ],
}
VITALS = {
    "systolic": 158, "diastolic": 94, "pulse_bpm": 96,
    "temperature": 36.8, "weight_kg": 72.5, "height_cm": 165,
    "source": "device",
    "sources": {"systolic": "device", "diastolic": "device", "pulse_bpm": "device",
                "temperature": "patient_input", "weight_kg": "patient_input",
                "height_cm": "patient_input"},
}

_checks = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global _checks
    _checks += 1
    if ok:
        print(f"  ok   {label}" + (f" — {detail}" if detail else ""))
        return
    print(f"  FAIL {label}" + (f" — {detail}" if detail else ""))
    raise SystemExit(1)


async def seed_disposition(conn: asyncpg.Connection, session_id: str) -> str:
    """Write the rows a completed screening turn would have written.

    Mirrors TriageService._finalize_chat_turn minus the model call: the
    classification on session metadata, one severity assessment, and the
    pending review the nurse will act on.
    """
    dept_id = await conn.fetchval(
        "SELECT id FROM departments WHERE code = 'opd_internal_medicine'"
    )
    if dept_id is None:
        raise SystemExit("departments not seeded — run scripts/init_db.py")

    metadata = json.loads(
        await conn.fetchval("SELECT metadata::text FROM sessions WHERE id = $1", session_id)
    )
    metadata["triage_classification"] = CLASSIFICATION
    metadata["vitals"] = VITALS
    await conn.execute(
        "UPDATE sessions SET metadata = $2::jsonb WHERE id = $1",
        uuid.UUID(session_id),
        json.dumps(metadata),
    )
    msg_id = await conn.fetchval(
        """
        INSERT INTO messages (session_id, role, input_mode, content)
        VALUES ($1, 'user', 'voice', 'แน่นหน้าอกมา 2 ชั่วโมง') RETURNING id
        """,
        uuid.UUID(session_id),
    )
    assessment_id = await conn.fetchval(
        """
        INSERT INTO severity_assessments (
            session_id, source_message_id, severity, confidence, explanation, detected_triggers
        ) VALUES ($1, $2, 'urgent', 0.9, $3, '[]'::jsonb) RETURNING id
        """,
        uuid.UUID(session_id),
        msg_id,
        CLASSIFICATION["key_reason"],
    )
    await conn.execute(
        """
        INSERT INTO assessment_reviews (session_id, assessment_id, proposed_department_id, status)
        VALUES ($1, $2, $3, 'pending')
        """,
        uuid.UUID(session_id),
        assessment_id,
        dept_id,
    )
    return str(assessment_id)


async def main() -> int:
    his_headers = {"X-API-Key": HIS_KEY}

    async with httpx.AsyncClient(timeout=20.0) as http:
        print("1. resolve the HN's current visit, then reset it")
        patient = (
            await http.get(f"{HIS}/api/v1/patients/{HN}", headers=his_headers)
        ).json()
        visit_id = (patient.get("current_visit") or {}).get("visit_id")
        check("HN has a current visit in the mock", bool(visit_id), str(visit_id))
        r = await http.post(
            f"{HIS}/api/admin/reset", headers=his_headers,
            json={"visit_ids": [visit_id], "reset_history": False},
        )
        check("mock HIS reachable + reset", r.status_code == 200, f"HTTP {r.status_code}")

        print("2. booth session linked to the patient (HN-first)")
        session = (await http.post(f"{API}/sessions", json={"language": "th"})).json()
        session_id = session["id"]
        link = await http.post(
            f"{API}/sessions/{session_id}/link-patient", json={"hn": HN}
        )
        check("link-patient validated against the HIS", link.json().get("linked") is True)

        print("3. seed the disposition (no LLM)")
        conn = await asyncpg.connect(DB)
        try:
            assessment_id = await seed_disposition(conn, session_id)
        finally:
            await conn.close()
        check("pending review created", bool(assessment_id), assessment_id)

        print("4. nurse logs in")
        login = await http.post(
            f"{API}/admin/login", json={"email": EMAIL, "password": PASSWORD}
        )
        check("nurse login", login.status_code == 200, f"HTTP {login.status_code}")
        auth = {"Authorization": f"Bearer {login.json()['access_token']}"}

        print("5. SBAR preview")
        preview = await http.post(
            f"{API}/admin/reviews/{assessment_id}/sbar-preview", headers=auth,
            json={"chief_complaint": None, "illness_note": None},
        )
        check("preview returns 200", preview.status_code == 200, f"HTTP {preview.status_code}")
        sbar = preview.json()
        check("has all seven SBAR fields", len(sbar) == 7, ", ".join(sorted(sbar)))
        check(
            "situation is Thai",
            any("฀" <= c <= "๿" for c in (sbar.get("situation") or "")),
            sbar.get("situation") or "",
        )
        check("triage level is in the assessment", "ระดับคัดกรอง 3" in (sbar.get("assessment") or ""))
        check("manual citation carried through", "MFU" in (sbar.get("assessment_problem") or ""))
        check("equipment left for the nurse", sbar.get("assessment_equipment") is None)

        print("6. nurse edits the handover, then approves")
        edited = dict(sbar)
        edited["assessment_equipment"] = "ECG monitor"
        edited["situation"] = "พยาบาลแก้ไข: " + (sbar.get("situation") or "")
        approve = await http.post(
            f"{API}/admin/reviews/{assessment_id}/approve", headers=auth,
            json={"chief_complaint": None, "illness_note": None, "sbar": edited},
        )
        check("approve returns 200", approve.status_code == 200, f"HTTP {approve.status_code}")
        review = approve.json()
        check(
            "hospital queued the patient",
            review.get("his_routing_status") == "pushed",
            f"status={review.get('his_routing_status')} msg={review.get('his_routing_message_th')}",
        )
        queue_number = review.get("his_queue_number")
        check("queue number returned to the nurse", bool(queue_number), str(queue_number))

        print("7. hospital side reflects the assignment")
        visit = (await http.get(f"{HIS}/api/visits/{visit_id}", headers=his_headers)).json()
        check("visit is routed", visit["screening_status"] == "routed")
        check(
            "destination service point recorded",
            visit["second_location"]["id"] == "SP_OPD_MED_01",
            str(visit["second_location"]["id"]),
        )
        check(
            "the NURSE-EDITED situation is what the hospital stored",
            visit["nurse_chief_complaint"] == edited["situation"],
            visit["nurse_chief_complaint"] or "",
        )

        print("8. re-approve is idempotent (double-booking regression)")
        again = await http.post(
            f"{API}/admin/reviews/{assessment_id}/approve", headers=auth,
            json={"chief_complaint": None, "illness_note": None, "sbar": edited},
        )
        second = again.json()
        check(
            "same queue number, not a second queue",
            second.get("his_queue_number") == queue_number,
            f"{second.get('his_queue_number')} vs {queue_number}",
        )
        check(
            "same request_id reused",
            second.get("his_request_id") == review.get("his_request_id"),
            str(second.get("his_request_id")),
        )

    print(f"\nAll {_checks} checks passed. Queue number handed to the patient: {queue_number}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {type(exc).__name__}: {exc}")
        sys.exit(1)
