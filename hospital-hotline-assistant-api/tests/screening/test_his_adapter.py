"""HIS adapter tests.

MockHisAdapter is exercised directly; HttpHisAdapter is driven against an
inline httpx.MockTransport that mimics the hospital HIS endpoints — no
network, no cross-package import.
"""

import json

import httpx
import pytest

from app.services.screening.his import (
    HttpHisAdapter,
    MockHisAdapter,
    PatientHistory,
    his_department_name,
)
from app.services.screening.his.http_adapter import _age_from_birthdate


# --- department map ----------------------------------------------------------

def test_department_map_covers_all_engine_codes():
    from app.services.screening.templates import DEPARTMENT_NAMES

    for code in DEPARTMENT_NAMES:
        assert his_department_name(code), f"no HIS name for {code}"
    assert his_department_name("emergency").startswith("แผนก ER")
    assert his_department_name(None) is None
    assert his_department_name("unknown_code") is None


# --- age computation ---------------------------------------------------------

def test_age_from_birthdate():
    # deterministic: person born 1900 is >100 but <130, so accepted
    assert _age_from_birthdate("1900-01-01") is not None
    assert _age_from_birthdate("") is None
    assert _age_from_birthdate("not-a-date") is None
    # datetime-suffixed ISO string is tolerated (takes first 10 chars)
    assert _age_from_birthdate("1990-06-15T00:00:00") is not None


# --- MockHisAdapter ----------------------------------------------------------

async def test_mock_adapter_validate_and_writes():
    mock = MockHisAdapter()
    assert await mock.validate_visit("") is None
    info = await mock.validate_visit("V123")
    assert info is not None and info.visit_id == "V123"
    assert info.patient_history is not None and info.patient_history.is_first_time is True
    assert await mock.push_referral({"visit_id": "V123"}) is True
    assert await mock.push_patient_history("HN1", {"smoking_alcohol": "none"}) is True
    assert await mock.confirm_routing(
        "V123", department="OPD", confirmed_by="nurse", rerouted=False
    ) is True


# --- HttpHisAdapter against a fake HIS ---------------------------------------

def _fake_his_handler():
    state = {"prescreens": {}}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-API-Key") == "k"
        path = request.url.path
        if request.method == "GET" and path == "/api/visits/V1":
            return httpx.Response(200, json={
                "visit_id": "V1", "hn": "HN1", "birthdate": "1980-05-01",
                "appointment": True,
                "vitals": {"systolic": 120, "diastolic": 80},
                "patient": {
                    "hn": "HN1",
                    "is_first_time": False,
                    "history": {
                        "smoking_alcohol": "smokes daily",
                        "allergies": "penicillin",
                        "chronic_conditions": "hypertension",
                        "past_surgeries": None,
                        "family_history": "father: diabetes",
                    },
                    "last_vitals": {
                        "weight": 70.5, "height": 171, "measured_at": "2025-01-01",
                    },
                },
            })
        if request.method == "GET" and path == "/api/visits/V2":
            # Visit with no nested patient object at all (e.g. an HIS that
            # doesn't support HN-level history yet).
            return httpx.Response(200, json={
                "visit_id": "V2", "hn": "HN2", "birthdate": "1990-01-01",
            })
        if request.method == "GET" and path == "/api/visits/MISSING":
            return httpx.Response(404, json={"detail": "not found"})
        if request.method == "POST" and path == "/api/visits/V1/prescreen":
            body = json.loads(request.content)
            state["prescreens"]["V1"] = body
            return httpx.Response(201, json={"status": "pending"})
        if request.method == "PUT" and path == "/api/visits/V1/routing":
            state["routing"] = json.loads(request.content)
            return httpx.Response(200, json={"status": "confirmed"})
        if request.method == "PUT" and path == "/api/patients/HN1/history":
            state["patient_history"] = json.loads(request.content)
            return httpx.Response(200, json={"hn": "HN1", "is_first_time": False})
        if request.method == "GET" and path == "/api/departments":
            return httpx.Response(200, json={"departments": ["แผนก ER (อุบัติเหตุและฉุกเฉิน)"]})
        return httpx.Response(500)

    return handler, state


def _adapter_with(handler) -> HttpHisAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://his")
    return HttpHisAdapter(base_url="http://his", api_key="k", client=client)


async def test_http_validate_visit_returns_age_and_vitals():
    handler, _ = _fake_his_handler()
    adapter = _adapter_with(handler)
    info = await adapter.validate_visit("V1")
    assert info is not None
    assert info.patient_id == "HN1"
    assert info.birthdate == "1980-05-01"
    assert info.age_years and info.age_years > 40
    assert info.vitals["systolic"] == 120
    assert info.appointment is True


async def test_http_validate_visit_parses_nested_patient_history():
    handler, _ = _fake_his_handler()
    adapter = _adapter_with(handler)
    info = await adapter.validate_visit("V1")
    assert info is not None
    history = info.patient_history
    assert isinstance(history, PatientHistory)
    assert history.is_first_time is False
    assert history.smoking_alcohol == "smokes daily"
    assert history.chronic_conditions == "hypertension"
    assert history.last_weight_kg == 70.5
    assert history.last_height_cm == 171
    assert history.vitals_measured_at == "2025-01-01"


async def test_http_validate_visit_without_patient_object_is_none():
    handler, _ = _fake_his_handler()
    adapter = _adapter_with(handler)
    info = await adapter.validate_visit("V2")
    assert info is not None
    assert info.patient_id == "HN2"
    assert info.patient_history is None


async def test_http_push_patient_history():
    handler, state = _fake_his_handler()
    adapter = _adapter_with(handler)
    ok = await adapter.push_patient_history("HN1", {"smoking_alcohol": "quit 2020"})
    assert ok is True
    assert state["patient_history"]["smoking_alcohol"] == "quit 2020"


async def test_http_validate_visit_unknown_returns_none():
    handler, _ = _fake_his_handler()
    adapter = _adapter_with(handler)
    assert await adapter.validate_visit("MISSING") is None
    assert await adapter.validate_visit("  ") is None


async def test_http_push_and_confirm():
    handler, state = _fake_his_handler()
    adapter = _adapter_with(handler)
    ok = await adapter.push_referral({
        "visit_id": "V1", "session_ref": "s", "recommended_department": "d",
    })
    assert ok is True
    assert state["prescreens"]["V1"]["session_ref"] == "s"
    assert await adapter.confirm_routing(
        "V1", department="d", confirmed_by="nurse", rerouted=False
    ) is True
    # Nurse-edited narrative is forwarded on the Stage-2 confirm.
    assert await adapter.confirm_routing(
        "V1", department="d", complaint="edited complaint",
        note="edited illness note", confirmed_by="nurse", rerouted=True,
    ) is True
    assert state["routing"]["complaint"] == "edited complaint"
    assert state["routing"]["illness_note"] == "edited illness note"
    assert state["routing"]["rerouted"] is True


async def test_http_push_without_visit_id_is_false():
    handler, _ = _fake_his_handler()
    adapter = _adapter_with(handler)
    assert await adapter.push_referral({"session_ref": "s"}) is False


async def test_http_tolerates_transport_errors():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = httpx.AsyncClient(transport=httpx.MockTransport(boom), base_url="http://his")
    adapter = HttpHisAdapter(base_url="http://his", api_key="k", client=client)
    assert await adapter.validate_visit("V1") is None
    assert await adapter.push_referral({"visit_id": "V1"}) is False
    assert await adapter.push_patient_history("HN1", {"smoking_alcohol": "x"}) is False
    assert await adapter.confirm_routing("V1", department="d", confirmed_by="n") is False
    assert await adapter.get_departments() == []
