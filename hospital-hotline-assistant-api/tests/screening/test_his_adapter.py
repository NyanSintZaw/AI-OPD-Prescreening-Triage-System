"""HIS adapter tests.

MockHisAdapter is exercised directly; HttpHisAdapter is driven against an
inline httpx.MockTransport that mimics the hospital HIS endpoints (Data
Requirements V1 shapes) — no network, no cross-package import.
"""

import json

import httpx
import pytest

from app.services.screening.his import (
    HttpHisAdapter,
    MockHisAdapter,
    PatientHistory,
    his_department_id,
    his_department_name,
    pdf_vitals,
)
from app.services.screening.his.http_adapter import _age_from_birthdate


# --- department map ----------------------------------------------------------

def test_department_map_covers_all_engine_codes():
    from app.services.screening.templates import DEPARTMENT_NAMES

    for code in DEPARTMENT_NAMES:
        assert his_department_name(code), f"no HIS name for {code}"
        # V1 routes at department granularity: every routable code needs a
        # base_department_id, or Stage 2 records a skip instead of pushing.
        assert his_department_id(code), f"no department id for {code}"
    assert his_department_name("emergency").startswith("แผนก ER")
    assert his_department_id("emergency") == "DEPT_ER"
    assert his_department_name(None) is None
    assert his_department_id(None) is None
    assert his_department_id("unknown_code") is None


# --- age computation ---------------------------------------------------------

def test_age_from_birthdate():
    # deterministic: person born 1900 is >100 but <130, so accepted
    assert _age_from_birthdate("1900-01-01") is not None
    assert _age_from_birthdate("") is None
    assert _age_from_birthdate("not-a-date") is None
    # datetime-suffixed ISO string is tolerated (takes first 10 chars)
    assert _age_from_birthdate("1990-06-15T00:00:00") is not None


# --- pdf_vitals projection ---------------------------------------------------

def test_pdf_vitals_projects_renames_and_derives_bmi():
    out = pdf_vitals({
        "systolic": 158, "diastolic": 94, "pulse_bpm": 96,
        "temperature": 36.8, "weight_kg": 72.5, "height_cm": 165,
        # internal junk that must never reach a hospital payload
        "source": "device", "recorded_at": "2026-08-20T09:00:00Z",
        "bp_recheck_pending": True, "spo2": 98, "measured_at": "x",
    })
    assert out["systolic"] == 158 and out["diastolic"] == 94
    assert out["temperature_c"] == 36.8       # wire rename
    assert out["hight_cm"] == 165             # the hospital's own spelling
    assert out["bmi"] == 26.63                # derived at send time
    for junk in ("source", "recorded_at", "bp_recheck_pending", "spo2",
                 "measured_at", "temperature", "height_cm"):
        assert junk not in out


def test_pdf_vitals_normalizes_sources_and_drops_his_provenance():
    out = pdf_vitals({
        "systolic": 120, "diastolic": 80, "temperature": 37.0,
        "weight_kg": 70, "height_cm": 170,
        "sources": {
            "systolic": "device", "diastolic": "device",
            "temperature": "manual",          # typed at the booth
            "weight_kg": "his_recent",        # HIS-carried — not in the enum
            "height_cm": "patient_input",
        },
    })
    src = out["sources"]
    assert src["systolic"] == "device"
    assert src["temperature_c"] == "patient_input"   # manual → patient_input
    assert src["hight_cm"] == "patient_input"
    assert "weight_kg" not in src   # HIS-sourced values carry no attribution


def test_pdf_vitals_omits_bmi_when_a_measurement_is_missing():
    assert "bmi" not in pdf_vitals({"weight_kg": 72.5})
    assert pdf_vitals(None) == {}


# --- MockHisAdapter ----------------------------------------------------------

async def test_mock_adapter_validate_and_writes():
    mock = MockHisAdapter()
    assert await mock.validate_patient("") is None
    info = await mock.validate_patient("09900001")
    assert info is not None and info.hn == "09900001"
    assert info.patient_history is not None and info.patient_history.is_first_time is True
    assert info.current_visit is None
    assert await mock.push_prescreen({"hn": "09900001"}) is True
    assert await mock.push_patient_history("HN1", {"smoking": "none"}) is True
    result = await mock.confirm_routing(
        None, request_id="MFU-1", hn="09900001", base_department_id="DEPT_MED"
    )
    assert result.status == "pushed" and result.queue_number


# --- HttpHisAdapter against a fake HIS ---------------------------------------

def _fake_his_handler():
    state = {"prescreens": {}}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-API-Key") == "k"
        assert request.headers.get("Authorization") == "Bearer k"
        path = request.url.path
        # One patient read gives the booth everything (V1 §1.2–1.4 + our
        # current_visit / gender extensions).
        if request.method == "GET" and path == "/api/v1/patients/HN1":
            return httpx.Response(200, json={
                "hn": "HN1",
                "patient_name": "สมชาย ใจดี",
                "birthdate": "1980-05-01",
                "gender": "male",
                "is_first_time": False,
                "history": {
                    "smoking": "smokes daily",
                    "alcohol": "no alcohol",
                    "allergies": "penicillin",
                    "chronic_conditions": "hypertension",
                    "post_surgeries": None,
                    "family_history": "father: diabetes",
                    "recorded_at": "2025-01-01",
                },
                "last_vitals": {
                    "weight": 70.5, "hight": 171, "measured_at": "2025-01-01",
                },
                "current_visit": {"visit_id": "V1", "appointment": True},
            })
        if request.method == "GET" and path == "/api/v1/patients/HN2":
            # A first-time patient with no open visit today: screening still
            # starts; the write-backs later go HN-only.
            return httpx.Response(200, json={
                "hn": "HN2",
                "patient_name": "Anucha Thongdee",
                "birthdate": "1990-01-01",
                "gender": None,
                "is_first_time": True,
                "history": {"recorded_at": None},
                "last_vitals": {},
                "current_visit": None,
            })
        if request.method == "GET" and path == "/api/v1/patients/MISSING":
            return httpx.Response(404, json={"detail": "not found"})
        if request.method == "POST" and path == "/api/v1/patient-prescreens":
            body = json.loads(request.content)
            state["prescreens"][body.get("hn")] = body
            return httpx.Response(200, json={
                "request_id": body.get("session_ref", ""),
                "status": "STATUS_SUCCESS",
                "result": {"visit_id": body.get("visit_id"),
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
                    "visit_id": body.get("visit_id"),
                    "visit_queue_id": "VQ-1",
                    "assign_spid": "SP_OPD_MED_01",
                    "assign_eid": None,
                    "queue_number": "M001",
                    "queue_status": "WAITING",
                    "sbar_id": "SBAR-1" if body.get("sbar") else None,
                },
            })
        if request.method == "PUT" and path == "/api/v1/patients/HN1/history":
            state["patient_history"] = json.loads(request.content)
            return httpx.Response(200, json={"hn": "HN1", "written": True})
        return httpx.Response(500)

    return handler, state


def _adapter_with(handler) -> HttpHisAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://his")
    return HttpHisAdapter(base_url="http://his", api_key="k", client=client)


async def test_http_validate_patient_returns_demographics_and_visit():
    handler, _ = _fake_his_handler()
    adapter = _adapter_with(handler)
    info = await adapter.validate_patient("HN1")
    assert info is not None
    assert info.hn == "HN1"
    assert info.patient_name == "สมชาย ใจดี"
    assert info.birthdate == "1980-05-01"
    assert info.age_years and info.age_years > 40
    assert info.gender == "male"
    assert info.is_first_time is False
    # The current visit rides along as the write-backs' VN passthrough.
    assert info.current_visit is not None
    assert info.current_visit.visit_id == "V1"
    assert info.current_visit.appointment is True


async def test_http_validate_patient_parses_split_history():
    handler, _ = _fake_his_handler()
    adapter = _adapter_with(handler)
    info = await adapter.validate_patient("HN1")
    assert info is not None
    history = info.patient_history
    assert isinstance(history, PatientHistory)
    assert history.is_first_time is False
    assert history.smoking == "smokes daily"
    assert history.alcohol == "no alcohol"
    assert history.chronic_conditions == "hypertension"
    assert history.last_weight_kg == 70.5
    assert history.last_height_cm == 171          # parsed from "hight"
    assert history.vitals_measured_at == "2025-01-01"


async def test_http_validate_patient_first_time_without_visit():
    handler, _ = _fake_his_handler()
    adapter = _adapter_with(handler)
    info = await adapter.validate_patient("HN2")
    assert info is not None
    assert info.is_first_time is True
    assert info.gender is None
    assert info.current_visit is None   # no open visit — screening still runs


async def test_http_push_patient_history():
    handler, state = _fake_his_handler()
    adapter = _adapter_with(handler)
    ok = await adapter.push_patient_history("HN1", {"smoking": "quit 2020"})
    assert ok is True
    assert state["patient_history"]["smoking"] == "quit 2020"


async def test_http_validate_patient_unknown_returns_none():
    handler, _ = _fake_his_handler()
    adapter = _adapter_with(handler)
    assert await adapter.validate_patient("MISSING") is None
    assert await adapter.validate_patient("  ") is None


async def test_http_push_and_confirm():
    handler, state = _fake_his_handler()
    adapter = _adapter_with(handler)
    ok = await adapter.push_prescreen({
        "visit_id": "V1", "hn": "HN1", "session_ref": "s",
    })
    assert ok is True
    assert state["prescreens"]["HN1"]["session_ref"] == "s"
    mfu = {"triage_level": 3, "triage_scale": "MOPH-5"}
    result = await adapter.confirm_routing(
        "V1", request_id="MFU-20260807-AAA111", hn="HN1",
        base_department_id="DEPT_MED",
        sbar={"situation": "แน่นหน้าอก", "assessment_equipment": None},
        mfu_prescreen=mfu,
    )
    assert result.status == "pushed"
    assert result.queue_number == "M001"
    assert result.visit_queue_id == "VQ-1"
    assert result.sbar_id == "SBAR-1"
    sent = state["assignment"]
    assert sent["request_id"] == "MFU-20260807-AAA111"
    # V1 §4.4 golden body: department granularity + hn + our screening block.
    assert sent["base_department_id"] == "DEPT_MED"
    assert sent["hn"] == "HN1"
    assert sent["visit_id"] == "V1"
    assert sent["mfu_prescreen"] == mfu
    # Empty SBAR fields are dropped rather than sent as nulls.
    assert sent["sbar"] == {"situation": "แน่นหน้าอก"}
    # Never sent: the hospital owns service-point selection and sequencing.
    assert "assign_spid" not in sent
    assert "queue_number" not in sent
    assert "assign_eid" not in sent


async def test_confirm_without_visit_passthrough_sends_hn_only():
    handler, state = _fake_his_handler()
    adapter = _adapter_with(handler)
    result = await adapter.confirm_routing(
        None, request_id="R-HN", hn="HN2", base_department_id="DEPT_GP"
    )
    assert result.status == "pushed"
    sent = state["assignment"]
    assert sent["visit_id"] is None
    assert sent["hn"] == "HN2"


async def test_prescreen_carries_pdf_vitals_shape():
    """§4.3 wire shape: renamed keys, hight_cm spelling, per-vital sources,
    bmi derived at send time, measured_at hoisted to the top level."""
    handler, state = _fake_his_handler()
    adapter = _adapter_with(handler)
    await adapter.push_prescreen({
        "visit_id": "V1", "hn": "HN1",
        "vitals": {"weight_kg": 72.5, "height_cm": 165, "systolic": 158,
                   "diastolic": 94, "temperature": 36.8,
                   "measured_at": "2026-08-20T09:12:00+07:00",
                   "sources": {"systolic": "device", "diastolic": "device",
                               "temperature": "manual"}},
    })
    sent = state["prescreens"]["HN1"]
    assert sent["measured_at"] == "2026-08-20T09:12:00+07:00"
    vitals = sent["vitals"]
    assert vitals["bmi"] == 26.63
    assert vitals["hight_cm"] == 165
    assert vitals["temperature_c"] == 36.8
    assert vitals["sources"]["temperature_c"] == "patient_input"
    assert "height_cm" not in vitals and "temperature" not in vitals


async def test_http_push_without_hn_is_false():
    handler, _ = _fake_his_handler()
    adapter = _adapter_with(handler)
    assert await adapter.push_prescreen({"session_ref": "s"}) is False


async def test_http_tolerates_transport_errors():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = httpx.AsyncClient(transport=httpx.MockTransport(boom), base_url="http://his")
    adapter = HttpHisAdapter(base_url="http://his", api_key="k", client=client)
    assert await adapter.validate_patient("HN1") is None
    assert await adapter.push_prescreen({"hn": "HN1"}) is False
    assert await adapter.push_patient_history("HN1", {"smoking": "x"}) is False
    # A transport error is "unknown", NEVER "failed": the queue row may exist,
    # and calling it a failure invites a re-confirm that double-books.
    unknown = await adapter.confirm_routing(
        "V1", request_id="R1", hn="HN1", base_department_id="DEPT_MED"
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
        "V1", request_id="R1", hn="HN1", base_department_id="DEPT_MED"
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
    result = await adapter.confirm_routing(
        "V1", request_id="R1", hn="HN1", base_department_id="DEPT_MED"
    )
    assert (result.status, result.queue_number) == ("pushed", "M007")


async def test_assignment_non_json_body_is_unknown():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway</html>")

    adapter = _adapter_with(handler)
    result = await adapter.confirm_routing(
        "V1", request_id="R1", hn="HN1", base_department_id="DEPT_MED"
    )
    assert result.status == "unknown"


async def test_prescreen_never_carries_the_ai_recommendation():
    """Stage 1 is objective data only. If the department or the reasoning
    leaked into it, unreviewed machine judgement would reach the hospital
    before a nurse signed it off, and the confirm step would be decorative."""
    handler, state = _fake_his_handler()
    adapter = _adapter_with(handler)
    ok = await adapter.push_prescreen({
        "visit_id": "V1", "hn": "HN1", "session_ref": "s1", "slip_code": "MCH-1",
        # Junk a sloppy caller might include — must all be dropped.
        "recommended_department": "แผนก OPD MED (อายุรกรรม)",
        "complaint": "chest tightness", "reason": "cardiac risk factors",
        "reasons": ["rule fired"],
        "vitals": {"systolic": 158, "diastolic": 94},
    })
    assert ok is True
    sent = state["prescreens"]["HN1"]
    assert sent["visit_id"] == "V1"
    assert sent["vitals"]["systolic"] == 158
    # HN travels with the VN so the hospital can cross-check the pair.
    assert sent["hn"] == "HN1"
    # Their export's first/second location model: the booth is the first.
    assert sent["first_location"]["id"] == "AI-BOOTH-01"
    for leaked in ("recommended_department", "complaint", "reason", "reasons"):
        assert leaked not in sent
