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
    result = await mock.confirm_routing(
        "V123", request_id="MFU-1", assign_spid="SP_OPD_MED_01"
    )
    assert result.status == "pushed" and result.queue_number


# --- HttpHisAdapter against a fake HIS ---------------------------------------

def _fake_his_handler():
    state = {"prescreens": {}}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-API-Key") == "k"
        assert request.headers.get("Authorization") == "Bearer k"
        path = request.url.path
        # The visit read carries identity + age band + is-it-open only; the
        # history lives behind a separate patient read (see the proposals).
        if request.method == "GET" and path == "/api/v1/visits/V1":
            return httpx.Response(200, json={
                "visit_id": "V1", "hn": "HN1", "birthdate": "1980-05-01",
                "active": True, "appointment": True,
                "vitals": {"systolic": 120, "diastolic": 80},
            })
        if request.method == "GET" and path == "/api/v1/patients/HN1":
            return httpx.Response(200, json={
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
            })
        if request.method == "GET" and path == "/api/v1/visits/V2":
            return httpx.Response(200, json={
                "visit_id": "V2", "hn": "HN2", "birthdate": "1990-01-01",
                "active": True,
            })
        if request.method == "GET" and path == "/api/v1/patients/HN2":
            # Hospital declined the patient read, or has no record: the booth
            # must still work, it just asks the patient their history.
            return httpx.Response(404, json={"detail": "not found"})
        if request.method == "GET" and path == "/api/v1/visits/MISSING":
            return httpx.Response(404, json={"detail": "not found"})
        if request.method == "POST" and path == "/api/v1/patient-prescreens":
            body = json.loads(request.content)
            state["prescreens"]["V1"] = body
            return httpx.Response(200, json={
                "request_id": body.get("session_ref", ""),
                "status": "STATUS_SUCCESS",
                "result": {"visit_id": body["visit_id"],
                           "prescreen_status": "AWAITING_CONFIRMATION"},
            })
        if request.method == "POST" and path == "/api/v1/patient-assignments":
            body = json.loads(request.content)
            state["assignment"] = body
            # Canned reply, or whatever the test staged for this call.
            staged = state.get("assignment_reply")
            if staged is not None:
                return httpx.Response(staged[0], json=staged[1])
            return httpx.Response(200, json={
                "request_id": body["request_id"],
                "status": "STATUS_SUCCESS",
                "result": {
                    "visit_id": body["visit_id"],
                    "visit_queue_id": "VQ-1",
                    "assign_spid": body["assign_spid"],
                    "assign_eid": None,
                    "queue_number": "M001",
                    "queue_status": "WAITING",
                    "sbar_id": "SBAR-1" if body.get("sbar") else None,
                },
            })
        if request.method == "PUT" and path == "/api/v1/patients/HN1/history":
            state["patient_history"] = json.loads(request.content)
            return httpx.Response(200, json={"hn": "HN1", "is_first_time": False})
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
    result = await adapter.confirm_routing(
        "V1", request_id="MFU-20260807-AAA111", assign_spid="SP_OPD_MED_01",
        sbar={"situation": "แน่นหน้าอก", "assessment_equipment": None},
    )
    assert result.status == "pushed"
    assert result.queue_number == "M001"
    assert result.visit_queue_id == "VQ-1"
    assert result.sbar_id == "SBAR-1"
    sent = state["assignment"]
    assert sent["request_id"] == "MFU-20260807-AAA111"
    assert sent["assign_spid"] == "SP_OPD_MED_01"
    # Empty SBAR fields are dropped rather than sent as nulls.
    assert sent["sbar"] == {"situation": "แน่นหน้าอก"}
    # Never sent: the hospital owns these.
    assert "queue_number" not in sent
    assert "base_department_id" not in sent
    assert "assign_eid" not in sent


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
    # A transport error is "unknown", NEVER "failed": the queue row may exist,
    # and calling it a failure invites a re-confirm that double-books.
    unknown = await adapter.confirm_routing(
        "V1", request_id="R1", assign_spid="SP_OPD_MED_01"
    )
    assert unknown.status == "unknown"
    assert unknown.request_id == "R1"


# --- assignment outcome mapping ----------------------------------------------
# The whole table, because each status drives a different nurse action and a
# wrong mapping tells the nurse to do the wrong thing.

@pytest.mark.parametrize(
    "code,body,expected",
    [
        (200, {"status": "STATUS_SUCCESS", "result": {"queue_number": "M001"}}, "pushed"),
        # 2xx but the hospital says it didn't work — our payload is wrong.
        (200, {"status": "STATUS_BUSINESS_ERROR", "message": "invalid_request"}, "invalid"),
        # Already queued: our earlier attempt landed, so this IS success.
        (409, {"status": "STATUS_BUSINESS_ERROR", "message": "VISIT_QUEUE_ALREADY_EXIST"}, "pushed"),
        (403, {"status": "STATUS_BUSINESS_ERROR", "message": "VISIT_LOCKED_OR_FINANCIAL_DISCHARGED"}, "denied"),
        (422, {"status": "STATUS_BUSINESS_ERROR", "message": "SERVICE_POINT_NOT_AVAILABLE"}, "unavailable"),
        # A framework validation 422 must NOT read as "department closed" —
        # that would send the nurse off to reroute a perfectly open clinic.
        (422, {"detail": [{"loc": ["body", "visit_id"]}]}, "invalid"),
        (400, {"status": "STATUS_BUSINESS_ERROR", "message": "invalid_request"}, "invalid"),
        # 5xx: the row may exist, so never a definite failure.
        (500, {"status": "STATUS_BUSINESS_ERROR"}, "unknown"),
    ],
)
async def test_assignment_status_mapping(code, body, expected):
    handler, state = _fake_his_handler()
    state["assignment_reply"] = (code, body)
    adapter = _adapter_with(handler)
    result = await adapter.confirm_routing(
        "V1", request_id="R1", assign_spid="SP_OPD_MED_01"
    )
    assert result.status == expected
    assert result.status != "failed"  # the word must never come back


async def test_assignment_409_carries_queue_number_when_hospital_returns_it():
    """Change request 7: if they return the original result on a duplicate we
    can still give the nurse a number; without it she must look it up."""
    handler, state = _fake_his_handler()
    state["assignment_reply"] = (409, {
        "status": "STATUS_BUSINESS_ERROR",
        "message": "VISIT_QUEUE_ALREADY_EXIST",
        "result": {"queue_number": "M007", "queue_status": "WAITING"},
    })
    adapter = _adapter_with(handler)
    result = await adapter.confirm_routing("V1", request_id="R1", assign_spid="SP_X")
    assert (result.status, result.queue_number) == ("pushed", "M007")


async def test_assignment_non_json_body_is_unknown():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway</html>")

    adapter = _adapter_with(handler)
    result = await adapter.confirm_routing("V1", request_id="R1", assign_spid="SP_X")
    assert result.status == "unknown"


async def test_visit_read_survives_the_patient_read_being_refused():
    """The patient read is optional by design — the hospital may decline it.
    When it 404s the booth must still start; it just asks the patient their
    history instead of skipping the interview."""
    handler, _ = _fake_his_handler()
    adapter = _adapter_with(handler)
    info = await adapter.validate_visit("V2")
    assert info is not None            # the session can still start
    assert info.patient_id == "HN2"
    assert info.patient_history is None  # -> booth runs the history intake


async def test_inactive_visit_is_refused():
    """A locked or financially discharged visit must never be screened."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "visit_id": "V9", "hn": "HN9", "active": False,
        })

    assert await _adapter_with(handler).validate_visit("V9") is None


async def test_prescreen_never_carries_the_ai_recommendation():
    """Stage 1 is objective data only. If the department or the reasoning
    leaked into it, unreviewed machine judgement would reach the hospital
    before a nurse signed it off, and the confirm step would be decorative."""
    handler, state = _fake_his_handler()
    adapter = _adapter_with(handler)
    ok = await adapter.push_referral({
        "visit_id": "V1", "session_ref": "s1", "slip_code": "MCH-1",
        "recommended_department": "แผนก OPD MED (อายุรกรรม)",
        "complaint": "chest tightness", "reason": "cardiac risk factors",
        "reasons": ["rule fired"],
        "vitals": {"systolic": 158, "diastolic": 94},
    })
    assert ok is True
    sent = state["prescreens"]["V1"]
    assert sent["visit_id"] == "V1"
    assert sent["vitals"]["systolic"] == 158
    assert sent["location"]["id"] == "AI-BOOTH-01"
    for leaked in ("recommended_department", "complaint", "reason", "reasons"):
        assert leaked not in sent
