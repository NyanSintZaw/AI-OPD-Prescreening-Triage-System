"""Mock HIS API tests — drive the endpoints via httpx ASGI transport,
seeded from the committed synthetic sample."""

import httpx
import pytest

from his_mock.database import parse_pressure, seed_from_csv
from his_mock.main import build_app

API_KEY = "test-key"
HEADERS = {"X-API-Key": API_KEY}
SAMPLE_VISIT = "990000000000000001"
EMERGENCY_VISIT = "990000000000000002"  # BP 84/53 in the sample


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HIS_MOCK_API_KEY", API_KEY)
    # empty db in tmp; build_app seeds from sample_visits.csv when empty
    app = build_app(db_path=tmp_path / "test.db")
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://his")


def test_parse_pressure():
    assert parse_pressure("140/74") == (140, 74)
    assert parse_pressure(" 84 / 53 ") == (84, 53)
    assert parse_pressure("") == (None, None)
    assert parse_pressure("n/a") == (None, None)


async def test_get_visit_returns_demographics_and_vitals(client):
    resp = await client.get(f"/api/visits/{EMERGENCY_VISIT}", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["visit_id"] == EMERGENCY_VISIT
    assert body["birthdate"] == "1958-07-01"
    assert body["vitals"]["systolic"] == 84
    assert body["vitals"]["diastolic"] == 53


async def test_get_visit_requires_api_key(client):
    resp = await client.get(f"/api/visits/{SAMPLE_VISIT}")
    assert resp.status_code == 401


async def test_unknown_visit_404(client):
    resp = await client.get("/api/visits/does-not-exist", headers=HEADERS)
    assert resp.status_code == 404


async def test_two_stage_write_back(client):
    # stage 1: push prescreen
    resp = await client.post(
        f"/api/visits/{SAMPLE_VISIT}/prescreen",
        headers=HEADERS,
        json={
            "session_ref": "sess-1",
            "slip_code": "MCH-ABCD-1234",
            "recommended_department": "แผนก OPD GP (ทั่วไป ชั้น1)",
            "complaint": "cough 3 days",
            "vitals": {"systolic": 122, "diastolic": 78},
            "reasons": ["no red flags", "mild symptoms"],
        },
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"

    # visit's first_location now stamped as the booth
    visit = (await client.get(f"/api/visits/{SAMPLE_VISIT}", headers=HEADERS)).json()
    assert visit["first_location"]["id"] == "AI-BOOTH-01"

    # stage 2: nurse confirms
    resp = await client.put(
        f"/api/visits/{SAMPLE_VISIT}/routing",
        headers=HEADERS,
        json={
            "department": "แผนก OPD GP (ทั่วไป ชั้น1)",
            "confirmed_by": "nurse.somchai",
            "rerouted": False,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed"

    visit = (await client.get(f"/api/visits/{SAMPLE_VISIT}", headers=HEADERS)).json()
    assert visit["second_location"]["department"] == "แผนก OPD GP (ทั่วไป ชั้น1)"


async def test_reroute_marks_status(client):
    await client.post(
        f"/api/visits/{SAMPLE_VISIT}/prescreen",
        headers=HEADERS,
        json={"session_ref": "s", "recommended_department": "แผนก OPD GP (ทั่วไป ชั้น1)"},
    )
    resp = await client.put(
        f"/api/visits/{SAMPLE_VISIT}/routing",
        headers=HEADERS,
        json={
            "department": "แผนก OPD MED (อายุรกรรม)",
            "confirmed_by": "nurse.a",
            "rerouted": True,
        },
    )
    assert resp.json()["status"] == "rerouted"
    assert resp.json()["confirmed_department"] == "แผนก OPD MED (อายุรกรรม)"


async def test_routing_without_prescreen_conflicts(client):
    resp = await client.put(
        f"/api/visits/{SAMPLE_VISIT}/routing",
        headers=HEADERS,
        json={"department": "x", "confirmed_by": "n"},
    )
    assert resp.status_code == 409


async def test_departments_list(client):
    resp = await client.get("/api/departments", headers=HEADERS)
    assert resp.status_code == 200
    assert "แผนก ผู้ป่วยนอก(หน่วยคัดกรอง)" in resp.json()["departments"]
