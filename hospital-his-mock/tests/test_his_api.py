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


async def test_stage2_publishes_narrative_and_department(client):
    await client.post(f"/api/visits/{VISIT}/prescreen", headers=HEADERS, json=REFERRAL)
    resp = await client.put(
        f"/api/visits/{VISIT}/routing",
        headers=HEADERS,
        json={
            "department": "แผนก OPD GP (ทั่วไป ชั้น1)",
            "confirmed_by": "nurse.somchai",
            "rerouted": False,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed"

    visit = (await client.get(f"/api/visits/{VISIT}", headers=HEADERS)).json()
    assert visit["screening_status"] == "routed"
    # narrative promoted from the held pending record
    assert visit["nurse_chief_complaint"] == REFERRAL["complaint"]
    assert visit["nurse_patient_illness"] == REFERRAL["reason"]
    assert visit["second_location"]["department"] == "แผนก OPD GP (ทั่วไป ชั้น1)"
    # measurements from stage 1 still present; waist_width still blank
    assert visit["vitals"]["pressure"] == "122/78"
    assert visit["vitals"]["waist_width"] is None


async def test_reroute_publishes_nurse_edited_narrative(client):
    await client.post(f"/api/visits/{VISIT}/prescreen", headers=HEADERS, json=REFERRAL)
    resp = await client.put(
        f"/api/visits/{VISIT}/routing",
        headers=HEADERS,
        json={
            "department": "แผนก OPD MED (อายุรกรรม)",
            "complaint": "nurse: chest tightness on exertion, 3 days",
            "illness_note": "nurse: needs internal medicine review",
            "confirmed_by": "nurse.a",
            "rerouted": True,
        },
    )
    assert resp.json()["status"] == "rerouted"
    visit = (await client.get(f"/api/visits/{VISIT}", headers=HEADERS)).json()
    assert visit["second_location"]["department"] == "แผนก OPD MED (อายุรกรรม)"
    assert visit["nurse_chief_complaint"] == "nurse: chest tightness on exertion, 3 days"
    assert visit["nurse_patient_illness"] == "nurse: needs internal medicine review"


async def test_confirm_without_edits_publishes_held_stage1_values(client):
    await client.post(f"/api/visits/{VISIT}/prescreen", headers=HEADERS, json=REFERRAL)
    resp = await client.put(
        f"/api/visits/{VISIT}/routing",
        headers=HEADERS,
        json={"department": REFERRAL["recommended_department"], "confirmed_by": "nurse.a"},
    )
    assert resp.json()["status"] == "confirmed"
    visit = (await client.get(f"/api/visits/{VISIT}", headers=HEADERS)).json()
    assert visit["nurse_chief_complaint"] == REFERRAL["complaint"]
    assert visit["nurse_patient_illness"] == REFERRAL["reason"]


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


async def test_routing_without_prescreen_conflicts(client):
    resp = await client.put(
        f"/api/visits/{VISIT}/routing",
        headers=HEADERS,
        json={"department": "x", "confirmed_by": "n"},
    )
    assert resp.status_code == 409


async def test_reset_single_visit_back_to_registered(client):
    # Drive the visit all the way to routed, then reset just it.
    await client.post(f"/api/visits/{VISIT}/prescreen", headers=HEADERS, json=REFERRAL)
    await client.put(
        f"/api/visits/{VISIT}/routing",
        headers=HEADERS,
        json={"department": "แผนก OPD GP (ทั่วไป ชั้น1)", "confirmed_by": "n"},
    )
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
