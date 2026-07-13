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


async def test_reroute_uses_nurse_note_for_illness(client):
    await client.post(f"/api/visits/{VISIT}/prescreen", headers=HEADERS, json=REFERRAL)
    resp = await client.put(
        f"/api/visits/{VISIT}/routing",
        headers=HEADERS,
        json={
            "department": "แผนก OPD MED (อายุรกรรม)",
            "complaint": "nurse: needs internal medicine review",
            "confirmed_by": "nurse.a",
            "rerouted": True,
        },
    )
    assert resp.json()["status"] == "rerouted"
    visit = (await client.get(f"/api/visits/{VISIT}", headers=HEADERS)).json()
    assert visit["second_location"]["department"] == "แผนก OPD MED (อายุรกรรม)"
    assert visit["nurse_patient_illness"] == "nurse: needs internal medicine review"


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
