"""Stage-1 HIS write-back logic in TriageService.

Exercises _maybe_push_referral directly with a recording fake adapter —
no DB, no engine — to prove the gating (linked visit + terminal
disposition + once-only) and the referral payload shaping.
"""

import pytest

from app.services.triage_service import TriageService, _disposition_reason_texts


class RecordingAdapter:
    def __init__(self, ok=True):
        self.ok = ok
        self.pushed = []
        self.confirmed = []

    async def validate_visit(self, visit_id):
        return None

    async def get_departments(self):
        return []

    async def push_referral(self, referral):
        self.pushed.append(referral)
        return self.ok

    async def confirm_routing(self, visit_id, *, department, complaint=None,
                              confirmed_by, rerouted=False):
        self.confirmed.append((visit_id, department, rerouted))
        return self.ok


def make_service(adapter):
    return TriageService(his_adapter=adapter)


# --- reason flattening -------------------------------------------------------

def test_disposition_reason_texts_handles_shapes():
    assert _disposition_reason_texts({"disposition_reasons": ["a", "b"]}) == ["a", "b"]
    structured = {
        "disposition_reasons": [
            {"rule_id": "r1", "text_en": "Low SpO2", "citation": "MFU p.12"},
            {"rule_id": "r2"},
        ]
    }
    assert _disposition_reason_texts(structured) == ["Low SpO2 (MFU p.12)", "r2"]
    assert _disposition_reason_texts({}) == []


# --- stage-1 gating ----------------------------------------------------------

async def _push(service, metadata, **kw):
    defaults = dict(
        session_id="s1",
        severity_level="general",
        department_code="opd_general",
        symptoms_summary="cough 3 days",
        classification={"disposition_reasons": ["no red flags"]},
    )
    defaults.update(kw)
    await service._maybe_push_referral(metadata=metadata, **defaults)


async def test_no_push_without_linked_visit():
    adapter = RecordingAdapter()
    service = make_service(adapter)
    meta = {"slip_code": "MCH-AAAA-BBBB"}
    await _push(service, meta)
    assert adapter.pushed == []
    assert "his_referral" not in meta


async def test_no_push_while_still_interviewing():
    adapter = RecordingAdapter()
    service = make_service(adapter)
    meta = {"visit": {"visit_id": "V1"}}
    await _push(service, meta, severity_level="unknown", department_code=None)
    assert adapter.pushed == []


async def test_push_on_terminal_disposition_maps_department():
    adapter = RecordingAdapter()
    service = make_service(adapter)
    meta = {
        "visit": {"visit_id": "V1"},
        "slip_code": "MCH-AAAA-BBBB",
        "vitals": {"systolic": 120, "diastolic": 80},
    }
    await _push(service, meta)
    assert len(adapter.pushed) == 1
    ref = adapter.pushed[0]
    assert ref["visit_id"] == "V1"
    assert ref["slip_code"] == "MCH-AAAA-BBBB"
    assert ref["recommended_department"] == "แผนก OPD GP (ทั่วไป ชั้น1)"
    assert ref["complaint"] == "cough 3 days"
    assert ref["reasons"] == ["no red flags"]
    assert meta["his_referral"]["status"] == "pushed"


async def test_push_is_once_only():
    adapter = RecordingAdapter()
    service = make_service(adapter)
    meta = {"visit": {"visit_id": "V1"}}
    await _push(service, meta)
    await _push(service, meta)  # repeat / post-completion turn
    assert len(adapter.pushed) == 1


async def test_emergency_department_pushed_as_emergency():
    adapter = RecordingAdapter()
    service = make_service(adapter)
    meta = {"visit": {"visit_id": "V1"}}
    await _push(service, meta, severity_level="emergency", department_code="emergency")
    assert adapter.pushed[0]["recommended_department"].startswith("แผนก ER")


async def test_failed_push_records_failed_status():
    adapter = RecordingAdapter(ok=False)
    service = make_service(adapter)
    meta = {"visit": {"visit_id": "V1"}}
    await _push(service, meta)
    assert meta["his_referral"]["status"] == "failed"


async def test_push_exception_never_raises():
    class Boom(RecordingAdapter):
        async def push_referral(self, referral):
            raise RuntimeError("HIS down")

    service = make_service(Boom())
    meta = {"visit": {"visit_id": "V1"}}
    await _push(service, meta)  # must not raise
    assert meta["his_referral"]["status"] == "failed"
