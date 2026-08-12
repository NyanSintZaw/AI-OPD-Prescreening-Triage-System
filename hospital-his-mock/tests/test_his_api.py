"""Mock HIS API tests — the before/after demo story.

Seeded from the committed pre-registration sample: visits start with only
registration fields; Stage-1 fills measurements + booth; Stage-2 (nurse
confirm) publishes the clinical narrative + department.
"""

import httpx
import pytest

from his_mock.database import parse_pressure
from his_mock.main import build_app

API_KEY = "test-key"
HEADERS = {"X-API-Key": API_KEY}
VISIT = "990000000000000001"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HIS_MOCK_API_KEY", API_KEY)
    app = build_app(db_path=tmp_path / "test.db")  # seeds pre-registration sample
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://his")


REFERRAL = {
    "session_ref": "sess-1",
    "slip_code": "MCH-ABCD-1234",
    "recommended_department": "แผนก OPD GP (ทั่วไป ชั้น1)",
    "complaint": "cough; findings: cough; onset: 3 days ago",
    "reason": "No emergency red flags; routine OPD assessment",
    "vitals": {"systolic": 122, "diastolic": 78, "pulse_bpm": 74,
               "weight_kg": 68, "height_cm": 170, "temperature": 36.6},
    "reasons": ["no red flags", "mild symptoms"],
}


# ── iMed assignment (POST /api/v1/patient-assignments) ──────────────────────
# The real contract authenticates with a Bearer token; the mock accepts
# X-API-Key too so one credential works against both endpoint families.
BEARER = {"Authorization": f"Bearer {API_KEY}"}
SPID_MED = "SP_OPD_MED_01"
SBAR = {
    "situation": "แน่นหน้าอกมา 2 ชั่วโมง",
    "background": "ความดันโลหิตสูง",
    "assessment": "BP 158/94 ระดับคัดกรอง 3",
    "assessment_problem": "เจ็บหน้าอกร่วมกับปัจจัยเสี่ยง",
    "recommend": "ส่งตรวจอายุรกรรม",
}


async def _assign(client, *, request_id="MFU-TEST-000001", spid=SPID_MED,
                  visit=VISIT, sbar=SBAR, headers=None):
    body = {"request_id": request_id, "visit_id": visit, "assign_spid": spid}
    if sbar is not None:
        body["sbar"] = sbar
    # `is None`, not `or` — an explicitly empty dict is how the no-auth case
    # is expressed, and `{} or BEARER` would silently authenticate it.
    return await client.post(
        "/api/v1/patient-assignments",
        headers=BEARER if headers is None else headers,
        json=body,
    )


def test_parse_pressure():
    assert parse_pressure("140/74") == (140, 74)
    assert parse_pressure("") == (None, None)
    assert parse_pressure("n/a") == (None, None)


async def test_visit_starts_in_registered_state(client):
    resp = await client.get(f"/api/visits/{VISIT}", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    # hospital-known fields present
    assert body["birthdate"]
    assert body["hnx"]
    assert body["screening_status"] == "registered"
    # every screening field blank
    assert body["vitals"]["pressure"] is None
    assert body["vitals"]["weight"] is None
    assert body["nurse_chief_complaint"] is None
    assert body["nurse_patient_illness"] is None
    assert body["first_location"]["department"] is None
    assert body["second_location"]["department"] is None


async def test_get_visit_requires_api_key(client):
    resp = await client.get(f"/api/visits/{VISIT}")
    assert resp.status_code == 401


async def test_unknown_visit_404(client):
    resp = await client.get("/api/visits/does-not-exist", headers=HEADERS)
    assert resp.status_code == 404


async def test_stage1_fills_measurements_and_booth_only(client):
    resp = await client.post(
        f"/api/visits/{VISIT}/prescreen", headers=HEADERS, json=REFERRAL
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"

    visit = (await client.get(f"/api/visits/{VISIT}", headers=HEADERS)).json()
    assert visit["screening_status"] == "screened"
    # measurements written from the booth
    assert visit["vitals"]["pressure"] == "122/78"
    assert visit["vitals"]["pulse"] == 74
    assert visit["vitals"]["weight"] == 68
    assert visit["vitals"]["bmi"] == round(68 / (1.70 ** 2), 2)
    # booth stamped as first_location + measure
    assert visit["first_location"]["id"] == "AI-BOOTH-01"
    assert visit["measure"]["department"]
    # clinical narrative + routing NOT published yet
    assert visit["nurse_chief_complaint"] is None
    assert visit["nurse_patient_illness"] is None
    assert visit["second_location"]["department"] is None
    # waist_width never touched
    assert visit["vitals"]["waist_width"] is None


async def test_visit_payload_includes_patient_name(client):
    visit = (await client.get(f"/api/visits/{VISIT}", headers=HEADERS)).json()
    assert visit["patient_name"] == "สมชาย ใจดี"
    assert visit["follow_up"] is None
    listed = (await client.get("/api/visits", headers=HEADERS)).json()["visits"]
    by_id = {v["visit_id"]: v for v in listed}
    assert by_id[VISIT]["patient_name"] == "สมชาย ใจดี"


async def test_follow_up_written_and_reset(client):
    resp = await client.put(
        f"/api/visits/{VISIT}/follow-up",
        headers=HEADERS,
        json={"follow_up": "Can I eat before the blood test?"},
    )
    assert resp.status_code == 200
    assert resp.json()["follow_up"] == "Can I eat before the blood test?"

    # reset clears follow_up but keeps the registration-owned name
    await client.post("/api/admin/reset", headers=HEADERS, json={"visit_ids": [VISIT]})
    visit = (await client.get(f"/api/visits/{VISIT}", headers=HEADERS)).json()
    assert visit["follow_up"] is None
    assert visit["patient_name"] == "สมชาย ใจดี"


async def test_follow_up_requires_api_key(client):
    resp = await client.put(
        f"/api/visits/{VISIT}/follow-up", json={"follow_up": "x"}
    )
    assert resp.status_code == 401


async def test_reset_single_visit_back_to_registered(client):
    # Drive the visit all the way to routed, then reset just it.
    await client.post(f"/api/visits/{VISIT}/prescreen", headers=HEADERS, json=REFERRAL)
    await _assign(client, request_id="RESET-1")
    resp = await client.post(
        "/api/admin/reset", headers=HEADERS, json={"visit_ids": [VISIT]}
    )
    assert resp.status_code == 200
    assert resp.json()["visit_ids"] == [VISIT]

    visit = (await client.get(f"/api/visits/{VISIT}", headers=HEADERS)).json()
    assert visit["screening_status"] == "registered"
    assert visit["vitals"]["pressure"] is None
    assert visit["vitals"]["weight"] is None
    assert visit["first_location"]["department"] is None
    assert visit["second_location"]["department"] is None
    assert visit["nurse_chief_complaint"] is None
    # pre-registration fields survive the reset
    assert visit["birthdate"] and visit["hnx"]
    # the held prescreen result is gone
    assert (await client.get(f"/api/visits/{VISIT}/prescreen", headers=HEADERS)).status_code == 404
    # ...and so is the queue row, so the same visit can be demoed again
    # instead of hitting the 409 duplicate path.
    again = await _assign(client, request_id="RESET-2")
    assert again.status_code == 200


async def test_reset_all_visits(client):
    await client.post(f"/api/visits/{VISIT}/prescreen", headers=HEADERS, json=REFERRAL)
    resp = await client.post("/api/admin/reset", headers=HEADERS, json={})
    assert resp.status_code == 200
    assert resp.json()["reset"] >= 6
    visits = (await client.get("/api/visits", headers=HEADERS)).json()["visits"]
    assert all(v["screening_status"] == "registered" for v in visits)


async def test_reset_requires_api_key(client):
    resp = await client.post("/api/admin/reset", json={})
    assert resp.status_code == 401


async def test_visit_payload_includes_hn_and_nested_patient(client):
    """§4.1: visit_payload emits both hnx and hn, plus the joined patient
    (HN master record) so a single GET gives the app everything it needs."""
    visit = (await client.get(f"/api/visits/{VISIT}", headers=HEADERS)).json()
    assert visit["hn"] == visit["hnx"] == "09900001"
    assert visit["patient"]["hn"] == "09900001"
    # 09900001 is seeded as a returning patient in sample_patients.csv.
    assert visit["patient"]["is_first_time"] is False
    assert visit["patient"]["history"]["chronic_conditions"]
    assert visit["patient"]["last_vitals"]["weight"] == 72.5


async def test_get_patient_returning_vs_first_time(client):
    returning = (await client.get("/api/patients/09900001", headers=HEADERS)).json()
    assert returning["is_first_time"] is False
    assert returning["history"]["recorded_at"]
    assert returning["last_vitals"]["height"] == 172

    first_time = (await client.get("/api/patients/09900003", headers=HEADERS)).json()
    assert first_time["is_first_time"] is True
    assert first_time["history"]["recorded_at"] is None
    assert first_time["history"]["chronic_conditions"] is None
    assert first_time["last_vitals"]["weight"] is None


async def test_list_patients(client):
    resp = await client.get("/api/patients", headers=HEADERS)
    assert resp.status_code == 200
    patients = resp.json()["patients"]
    by_hn = {p["hn"]: p for p in patients}
    # Every seeded visit's HN has a master record (backfill guarantees it).
    assert "09900001" in by_hn and "09900003" in by_hn
    returning = by_hn["09900001"]
    assert returning["is_first_time"] is False
    assert returning["history"]["chronic_conditions"]
    assert returning["visit_count"] >= 1
    assert by_hn["09900003"]["is_first_time"] is True


async def test_list_patients_requires_api_key(client):
    resp = await client.get("/api/patients")
    assert resp.status_code == 401


async def test_get_unknown_patient_404(client):
    resp = await client.get("/api/patients/does-not-exist", headers=HEADERS)
    assert resp.status_code == 404


async def test_get_patient_requires_api_key(client):
    resp = await client.get("/api/patients/09900001")
    assert resp.status_code == 401


async def test_first_visit_history_captured_then_returning(client):
    """Golden path: a first-time patient's booth-collected history is
    written back and immediately flips is_first_time to False, and
    persists on a later lookup (simulating a second visit)."""
    hn = "09900003"
    before = (await client.get(f"/api/patients/{hn}", headers=HEADERS)).json()
    assert before["is_first_time"] is True

    resp = await client.put(
        f"/api/patients/{hn}/history",
        headers=HEADERS,
        json={
            "smoking_alcohol": "Non-smoker; no alcohol",
            "allergies": "None known",
            "chronic_conditions": "None",
            "past_surgeries": "None",
            "family_history": "Father: hypertension",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_first_time"] is False
    assert body["history"]["family_history"] == "Father: hypertension"
    assert body["history"]["recorded_at"]

    # A later lookup (as if from a second visit) sees the same history and
    # no longer treats the patient as first-time.
    after = (await client.get(f"/api/patients/{hn}", headers=HEADERS)).json()
    assert after["is_first_time"] is False
    assert after["history"]["allergies"] == "None known"


async def test_update_patient_vitals_recorded_for_next_visit(client):
    hn = "09900004"
    resp = await client.put(
        f"/api/patients/{hn}/vitals",
        headers=HEADERS,
        json={"weight_kg": 55.5, "height_cm": 160},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["last_vitals"]["weight"] == 55.5
    assert body["last_vitals"]["height"] == 160
    assert body["last_vitals"]["measured_at"]

    fetched = (await client.get(f"/api/patients/{hn}", headers=HEADERS)).json()
    assert fetched["last_vitals"]["weight"] == 55.5


async def test_history_and_vitals_write_require_api_key(client):
    assert (await client.put(
        "/api/patients/09900001/history", json={"smoking_alcohol": "x"}
    )).status_code == 401
    assert (await client.put(
        "/api/patients/09900001/vitals", json={"weight_kg": 1}
    )).status_code == 401


async def test_write_history_for_unknown_patient_404(client):
    resp = await client.put(
        "/api/patients/does-not-exist/history",
        headers=HEADERS,
        json={"smoking_alcohol": "x"},
    )
    assert resp.status_code == 404


async def test_reset_visit_leaves_history_alone_by_default(client):
    """reset_history defaults false: resetting a visit must not wipe the
    HN's carried-forward history — it's meant to persist across visits."""
    await client.post("/api/admin/reset", headers=HEADERS, json={"visit_ids": [VISIT]})
    patient = (await client.get("/api/patients/09900001", headers=HEADERS)).json()
    assert patient["is_first_time"] is False
    assert patient["history"]["chronic_conditions"]


async def test_reset_with_reset_history_wipes_affected_patient(client):
    resp = await client.post(
        "/api/admin/reset",
        headers=HEADERS,
        json={"visit_ids": [VISIT], "reset_history": True},
    )
    assert resp.status_code == 200
    patient = (await client.get("/api/patients/09900001", headers=HEADERS)).json()
    assert patient["is_first_time"] is True
    assert patient["history"]["chronic_conditions"] is None
    assert patient["last_vitals"]["weight"] is None
    # Unaffected patient (different visit) keeps its history.
    other = (await client.get("/api/patients/09900002", headers=HEADERS)).json()
    assert other["is_first_time"] is False


async def test_reset_all_with_reset_history_wipes_every_patient(client):
    await client.post(
        "/api/admin/reset", headers=HEADERS, json={"reset_history": True}
    )
    for hn in ("09900001", "09900002", "09900005", "09900007"):
        patient = (await client.get(f"/api/patients/{hn}", headers=HEADERS)).json()
        assert patient["is_first_time"] is True


async def test_list_visits_reports_status(client):
    resp = await client.get("/api/visits", headers=HEADERS)
    assert resp.status_code == 200
    visits = resp.json()["visits"]
    assert len(visits) >= 6
    assert all(v["screening_status"] == "registered" for v in visits)
    # after a stage-1 push, that visit flips to screened
    await client.post(f"/api/visits/{VISIT}/prescreen", headers=HEADERS, json=REFERRAL)
    visits = (await client.get("/api/visits", headers=HEADERS)).json()["visits"]
    by_id = {v["visit_id"]: v for v in visits}
    assert by_id[VISIT]["screening_status"] == "screened"


async def test_assignment_success_envelope(client):
    resp = await _assign(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "STATUS_SUCCESS"
    assert body["request_id"] == "MFU-TEST-000001"
    result = body["result"]
    assert result["visit_id"] == VISIT
    assert result["assign_spid"] == SPID_MED
    assert result["queue_status"] == "WAITING"
    assert result["queue_number"].startswith("M")
    assert result["visit_queue_id"].startswith("VQ-")
    assert result["sbar_id"].startswith("SBAR-")


async def test_assignment_without_sbar_has_no_sbar_id(client):
    result = (await _assign(client, sbar=None)).json()["result"]
    assert result["sbar_id"] is None


async def test_assignment_accepts_either_auth_header_and_rejects_none(client):
    assert (await _assign(client, request_id="A1", headers=BEARER)).status_code == 200
    # X-API-Key path — a different visit so it isn't a duplicate queue
    r = await _assign(client, request_id="A2", visit="990000000000000002", headers=HEADERS)
    assert r.status_code == 200
    assert (await _assign(client, request_id="A3", headers={})).status_code == 401


async def test_queue_numbers_increment_per_service_point(client):
    first = (await _assign(client, request_id="Q1")).json()["result"]["queue_number"]
    second = (
        await _assign(client, request_id="Q2", visit="990000000000000002")
    ).json()["result"]["queue_number"]
    assert (first, second) == ("M001", "M002")


async def test_same_request_id_replays_original_result(client):
    first = (await _assign(client, request_id="IDEM-1")).json()
    second = (await _assign(client, request_id="IDEM-1")).json()
    assert second == first  # idempotent: same queue number, no second row
    visit = (await client.get(f"/api/visits/{VISIT}", headers=HEADERS)).json()
    assert visit["second_location"]["id"] == SPID_MED


async def test_different_request_id_same_service_point_conflicts(client):
    await _assign(client, request_id="D1")
    resp = await _assign(client, request_id="D2")
    assert resp.status_code == 409
    assert resp.json()["message"] == "VISIT_QUEUE_ALREADY_EXIST"
    assert resp.json()["status"] == "STATUS_BUSINESS_ERROR"


async def test_assignment_publishes_service_point_onto_visit(client):
    """Regression: the retired PUT /routing hardcoded second_location_id=None,
    so the hospital row never carried the destination service-point id."""
    await _assign(client)
    visit = (await client.get(f"/api/visits/{VISIT}", headers=HEADERS)).json()
    assert visit["screening_status"] == "routed"
    assert visit["second_location"]["id"] == SPID_MED
    assert visit["second_location"]["name"] == "แผนก OPD MED (อายุรกรรม)"
    assert visit["nurse_chief_complaint"] == SBAR["situation"]
    assert visit["nurse_patient_illness"] == SBAR["assessment_problem"]


async def test_assignment_confirms_prescreen_when_one_exists(client):
    await client.post(f"/api/visits/{VISIT}/prescreen", headers=HEADERS, json=REFERRAL)
    await _assign(client)
    held = (await client.get(f"/api/visits/{VISIT}/prescreen", headers=HEADERS)).json()
    assert held["status"] == "confirmed"
    assert held["confirmed_department"] == "แผนก OPD MED (อายุรกรรม)"
    # iMed has no attribution field — the empty column IS change request 3.
    assert held["confirmed_by"] is None


async def test_assignment_succeeds_without_any_prescreen(client):
    """iMed knows nothing about our Stage 1, so an assignment must not
    depend on it (the retired endpoint 409'd here)."""
    assert (await _assign(client)).status_code == 200


async def test_reassign_elsewhere_cancels_the_previous_queue(client):
    await _assign(client, request_id="R1", spid=SPID_MED)
    resp = await _assign(client, request_id="R2", spid="SP_OPD_HEART_01")
    assert resp.status_code == 200
    visit = (await client.get(f"/api/visits/{VISIT}", headers=HEADERS)).json()
    assert visit["second_location"]["id"] == "SP_OPD_HEART_01"


async def test_locked_visit_is_forbidden(client, tmp_path):
    from his_mock.database import connect

    conn = connect(tmp_path / "test.db")
    conn.execute(
        "UPDATE visits SET visit_lock_status = 'LOCKED' WHERE visit_id = ?", (VISIT,)
    )
    conn.commit()
    resp = await _assign(client)
    assert resp.status_code == 403
    assert resp.json()["message"] == "VISIT_LOCKED_OR_FINANCIAL_DISCHARGED"


async def test_closed_service_point_is_unavailable(client, tmp_path):
    from his_mock.database import connect

    conn = connect(tmp_path / "test.db")
    conn.execute("UPDATE service_points SET is_open = 0 WHERE spid = ?", (SPID_MED,))
    conn.commit()
    resp = await _assign(client)
    assert resp.status_code == 422
    assert resp.json()["message"] == "SERVICE_POINT_NOT_AVAILABLE"


async def test_unknown_service_point_and_unknown_visit_are_invalid_request(client):
    bad_sp = await _assign(client, request_id="U1", spid="SP_NOPE")
    assert bad_sp.status_code == 400
    assert bad_sp.json()["message"] == "invalid_request"
    bad_visit = await _assign(client, request_id="U2", visit="does-not-exist")
    assert bad_visit.status_code == 400


async def test_malformed_body_is_400_not_422(client):
    """422 is reserved for SERVICE_POINT_NOT_AVAILABLE; FastAPI's default
    validation 422 would make our adapter tell the nurse the department is
    closed when the real problem is our payload."""
    resp = await client.post(
        "/api/v1/patient-assignments", headers=BEARER, json={"request_id": "M1"}
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == "invalid_request"



# ── /api/v1 proposals (change requests 6, 13, 14) ────────────────────────────
# Runnable so the hospital-facing Postman collection demos end to end. These
# are OUR proposed shapes, not iMed's contract.

async def test_v1_visit_lookup_returns_identity_and_age_band(client):
    r = await client.get(f"/api/v1/visits/{VISIT}", headers=BEARER)
    assert r.status_code == 200
    body = r.json()
    # exactly what the booth needs to safely START a session
    assert body["visit_id"] == VISIT
    assert body["hn"] and body["patient_name"] and body["birthdate"]
    assert body["active"] is True


async def test_v1_visit_lookup_reports_a_locked_visit_as_inactive(client, tmp_path):
    from his_mock.database import connect

    conn = connect(tmp_path / "test.db")
    conn.execute(
        "UPDATE visits SET visit_lock_status = 'LOCKED' WHERE visit_id = ?", (VISIT,)
    )
    conn.commit()
    assert (await client.get(f"/api/v1/visits/{VISIT}", headers=BEARER)).json()["active"] is False


async def test_v1_patient_read_and_history_write_round_trip(client):
    hn = "09900003"  # seeded WITHOUT a history — the first-time case

    before = (await client.get(f"/api/v1/patients/{hn}", headers=BEARER)).json()
    assert before["is_first_time"] is True
    assert before["history"]["recorded_at"] is None

    write = await client.put(
        f"/api/v1/patients/{hn}/history", headers=BEARER,
        json={"allergies": "แพ้ยาเพนนิซิลลิน", "chronic_conditions": "ความดันโลหิตสูง"},
    )
    assert write.status_code == 200 and write.json()["written"] is True

    after = (await client.get(f"/api/v1/patients/{hn}", headers=BEARER)).json()
    assert after["history"]["allergies"] == "แพ้ยาเพนนิซิลลิน"
    # recorded_at is now set, so the booth skips the history interview
    assert after["history"]["recorded_at"] and after["is_first_time"] is False


async def test_v1_history_write_never_overwrites_an_existing_history(client):
    """We only ever fill an empty history — the hospital's own record wins.

    09900001 is seeded as a returning patient, so the very first write must
    already be refused."""
    existing = (await client.get("/api/v1/patients/09900001", headers=BEARER)).json()
    kept = existing["history"]["chronic_conditions"]

    refused = await client.put("/api/v1/patients/09900001/history", headers=BEARER,
                               json={"chronic_conditions": "booth-supplied"})
    assert refused.json()["written"] is False
    after = (await client.get("/api/v1/patients/09900001", headers=BEARER)).json()
    assert after["history"]["chronic_conditions"] == kept


async def test_v1_departments_lists_every_routing_destination(client):
    """CR 18 — one row per department, not per service point, because a
    department is the only thing we ever assign."""
    body = (await client.get("/api/v1/departments", headers=BEARER)).json()
    ids = [d["id"] for d in body["departments"]]

    assert len(ids) == len(set(ids))
    assert {"DEPT_ER", "DEPT_MED"} <= set(ids)
    assert all(d["name"] and d["active"] is True for d in body["departments"])


async def test_v1_prescreen_records_measurements_but_no_judgement(client):
    r = await client.post(
        "/api/v1/patient-prescreens", headers=BEARER,
        json={
            "visit_id": VISIT, "session_ref": "sess-1", "slip_code": "MCH-A1B2-C3D4",
            "measured_at": "2026-08-07T09:12:00+07:00",
            "vitals": {"systolic": 158, "diastolic": 94, "pulse_bpm": 96,
                       "temperature_c": 36.8, "weight_kg": 72.5, "height_cm": 165},
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == "STATUS_SUCCESS"
    assert r.json()["result"]["prescreen_status"] == "AWAITING_CONFIRMATION"

    visit = (await client.get(f"/api/visits/{VISIT}", headers=HEADERS)).json()
    assert visit["vitals"]["pressure"] == "158/94"
    assert visit["vitals"]["temperature"] == 36.8
    # screened, NOT routed: no department was sent, and none was inferred
    assert visit["screening_status"] == "screened"
    assert visit["second_location"]["department"] is None


async def test_v1_prescreen_for_unknown_visit_is_invalid_request(client):
    r = await client.post("/api/v1/patient-prescreens", headers=BEARER,
                          json={"visit_id": "nope", "vitals": {}})
    assert r.status_code == 400 and r.json()["message"] == "invalid_request"


async def test_v1_assignment_lookup_returns_the_original_result_and_sbar(client):
    """CR 5/7/8: turns a timed-out assignment from a guess into a fact."""
    created = (await _assign(client, request_id="LOOKUP-1")).json()["result"]
    r = await client.get("/api/v1/patient-assignments/LOOKUP-1", headers=BEARER)
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["queue_number"] == created["queue_number"]
    assert result["sbar"]["situation"] == SBAR["situation"]


async def test_v1_assignment_lookup_unknown_request_id(client):
    r = await client.get("/api/v1/patient-assignments/never-sent", headers=BEARER)
    assert r.status_code == 404 and r.json()["status"] == "STATUS_BUSINESS_ERROR"


async def test_v1_endpoints_require_auth(client):
    for path in (f"/api/v1/visits/{VISIT}", "/api/v1/patients/09900001",
                 "/api/v1/patient-assignments/x"):
        assert (await client.get(path, headers={})).status_code == 401


async def test_v1_prescreen_rejects_a_visit_hn_mismatch(client):
    """The HN is not strictly needed — iMed derives the patient from the visit.
    We send it so a mismatch is caught BEFORE anything is written, rather than
    after a patient is recorded against the wrong record."""
    r = await client.post(
        "/api/v1/patient-prescreens", headers=BEARER,
        json={"visit_id": VISIT, "hn": "09999999", "vitals": {"systolic": 120, "diastolic": 80}},
    )
    assert r.status_code == 400
    assert r.json()["message"] == "invalid_request"
    # nothing was written
    visit = (await client.get(f"/api/visits/{VISIT}", headers=HEADERS)).json()
    assert visit["screening_status"] == "registered"


async def test_v1_prescreen_sets_first_location_leaving_second_for_the_assignment(client):
    """Their export's own model: booth = first location, destination = second."""
    await client.post(
        "/api/v1/patient-prescreens", headers=BEARER,
        json={
            "visit_id": VISIT, "hn": "09900001",
            "first_location": {"id": "AI-BOOTH-01", "name": "AI Pre-Screening Booth",
                               "department": "แผนก ผู้ป่วยนอก(หน่วยคัดกรอง)"},
            "vitals": {"systolic": 158, "diastolic": 94},
        },
    )
    visit = (await client.get(f"/api/visits/{VISIT}", headers=HEADERS)).json()
    assert visit["first_location"]["id"] == "AI-BOOTH-01"
    assert visit["second_location"]["department"] is None   # nurse hasn't confirmed

    await _assign(client, request_id="LOC-1")
    visit = (await client.get(f"/api/visits/{VISIT}", headers=HEADERS)).json()
    assert visit["first_location"]["id"] == "AI-BOOTH-01"   # booth survives
    assert visit["second_location"]["id"] == SPID_MED       # destination added


# ── gender on the patient record ─────────────────────────────────────────────

async def test_gender_seeded_and_exposed_on_reads(client):
    """Seeded gender surfaces on the patient read, the v1 visit lookup, and
    the nested patient object of the visit read."""
    patient = (await client.get("/api/patients/09900001", headers=HEADERS)).json()
    assert patient["gender"] == "male"
    v1 = (await client.get("/api/v1/visits/990000000000000001", headers=BEARER)).json()
    assert v1["gender"] == "male"
    visit = (await client.get("/api/visits/990000000000000001", headers=HEADERS)).json()
    assert visit["patient"]["gender"] == "male"


async def test_gender_null_patient_stays_null_until_booth_fills(client):
    """09900004 is seeded without a gender — the missing-data demo path."""
    patient = (await client.get("/api/patients/09900004", headers=HEADERS)).json()
    assert patient["gender"] is None
    v1 = (await client.get("/api/v1/visits/990000000000000004", headers=BEARER)).json()
    assert v1["gender"] is None


async def test_gender_write_fills_empty_only(client):
    hn = "09900004"
    resp = await client.put(
        f"/api/v1/patients/{hn}/gender", headers=BEARER, json={"gender": "female"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["written"] is True
    assert body["patient"]["gender"] == "female"

    # A second write NEVER overwrites — same rule as the history write-back.
    resp = await client.put(
        f"/api/v1/patients/{hn}/gender", headers=BEARER, json={"gender": "male"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["written"] is False
    assert body["patient"]["gender"] == "female"


async def test_gender_write_never_overwrites_hospital_value(client):
    resp = await client.put(
        "/api/v1/patients/09900002/gender", headers=BEARER, json={"gender": "male"}
    )
    assert resp.json()["written"] is False
    patient = (await client.get("/api/patients/09900002", headers=HEADERS)).json()
    assert patient["gender"] == "female"


async def test_gender_write_rejects_open_values_and_unknown_patient(client):
    resp = await client.put(
        "/api/v1/patients/09900004/gender", headers=BEARER, json={"gender": "yes"}
    )
    assert resp.status_code == 400  # /api/v1 validation maps to invalid_request
    resp = await client.put(
        "/api/v1/patients/no-such-hn/gender", headers=BEARER, json={"gender": "male"}
    )
    assert resp.status_code == 404


async def test_gender_column_patched_into_existing_db(tmp_path, monkeypatch):
    """A pre-gender DB file (like the committed his_mock.db) gets the column
    added by connect()'s ad-hoc migration instead of crashing."""
    import sqlite3

    from his_mock.database import connect

    db_path = tmp_path / "old.db"
    legacy = sqlite3.connect(db_path)
    legacy.execute("CREATE TABLE patients (hn TEXT PRIMARY KEY, patient_name TEXT)")
    legacy.execute("INSERT INTO patients (hn, patient_name) VALUES ('X1', 'Old Row')")
    legacy.commit()
    legacy.close()

    conn = connect(db_path)
    row = conn.execute("SELECT gender FROM patients WHERE hn = 'X1'").fetchone()
    assert row["gender"] is None
