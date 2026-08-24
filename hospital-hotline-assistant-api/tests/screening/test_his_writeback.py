"""Stage-1 HIS write-back logic in TriageService.

Exercises _maybe_push_prescreen directly with a recording fake adapter —
no DB, no engine — to prove the gating (linked patient + terminal
disposition + once-only + BP present) and the prescreen payload shaping.
"""

import pytest

from app.services.triage_service import TriageService, _disposition_reason_texts


class RecordingAdapter:
    def __init__(self, ok=True):
        self.ok = ok
        self.pushed = []
        self.confirmed = []

    async def validate_patient(self, hn):
        return None

    async def push_prescreen(self, prescreen):
        self.pushed.append(prescreen)
        return self.ok

    async def confirm_routing(self, visit_id, *, request_id, hn,
                              base_department_id, sbar=None, mfu_prescreen=None):
        self.confirmed.append((visit_id, hn, base_department_id))
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

# Every gating fixture carries a BP so only the gate under test varies; the
# no-BP skip has its own dedicated test.
_BP = {"systolic": 120, "diastolic": 80}


async def _push(service, metadata, **kw):
    defaults = dict(
        session_id="s1",
        severity_level="general",
        department_code="opd_general",
        symptoms_summary="cough 3 days",
        classification={"disposition_reasons": ["no red flags"]},
    )
    defaults.update(kw)
    await service._maybe_push_prescreen(metadata=metadata, **defaults)


async def test_no_push_without_linked_patient():
    adapter = RecordingAdapter()
    service = make_service(adapter)
    meta = {"slip_code": "MCH-AAAA-BBBB", "vitals": dict(_BP)}
    await _push(service, meta)
    assert adapter.pushed == []
    assert "his_prescreen" not in meta


async def test_no_push_while_still_interviewing():
    adapter = RecordingAdapter()
    service = make_service(adapter)
    meta = {"patient": {"hn": "09900001"}, "vitals": dict(_BP)}
    await _push(service, meta, severity_level="unknown", department_code=None)
    assert adapter.pushed == []


async def test_push_on_terminal_disposition_is_objective_only():
    adapter = RecordingAdapter()
    service = make_service(adapter)
    meta = {
        "patient": {"hn": "09900001", "visit_id": "V1"},
        "slip_code": "MCH-AAAA-BBBB",
        "vitals": {"systolic": 120, "diastolic": 80},
    }
    await _push(service, meta)
    assert len(adapter.pushed) == 1
    ref = adapter.pushed[0]
    assert ref["hn"] == "09900001"
    assert ref["visit_id"] == "V1"          # VN passthrough from link time
    assert ref["slip_code"] == "MCH-AAAA-BBBB"
    assert ref["session_ref"] == "s1"
    assert ref["vitals"]["systolic"] == 120
    # The AI's judgement never rides in Stage 1 (V1 §4.3) — it stays in OUR
    # metadata for the nurse and travels only at Stage 2.
    for held_back in ("recommended_department", "complaint", "reason", "reasons"):
        assert held_back not in ref
    assert meta["his_prescreen"]["status"] == "pushed"
    # The recommendation is still recorded on our side for the nurse view.
    assert meta["his_prescreen"]["his_department"] == "แผนก OPD GP (ทั่วไป ชั้น1)"


async def test_push_without_visit_passthrough_still_fires():
    """HN-only patient (no open visit at link time): the prescreen still goes,
    with visit_id null — the HIS resolves the active visit itself."""
    adapter = RecordingAdapter()
    service = make_service(adapter)
    meta = {"patient": {"hn": "09900002"}, "vitals": dict(_BP)}
    await _push(service, meta)
    assert len(adapter.pushed) == 1
    assert adapter.pushed[0]["visit_id"] is None
    assert adapter.pushed[0]["hn"] == "09900002"


async def test_no_bp_records_skip_not_fake_numbers():
    """V1 marks systolic/diastolic required, but a patient may refuse the
    cuff. We never invent numbers — the push is skipped with a visible
    reason instead."""
    adapter = RecordingAdapter()
    service = make_service(adapter)
    meta = {"patient": {"hn": "09900001"}, "vitals": {"temperature": 36.8}}
    await _push(service, meta)
    assert adapter.pushed == []
    assert meta["his_prescreen"]["status"] == "skipped"
    assert meta["his_prescreen"]["reason"] == "no_bp"


async def test_push_is_once_only():
    adapter = RecordingAdapter()
    service = make_service(adapter)
    meta = {"patient": {"hn": "09900001"}, "vitals": dict(_BP)}
    await _push(service, meta)
    await _push(service, meta)  # repeat / post-completion turn
    assert len(adapter.pushed) == 1


async def test_emergency_department_recorded_as_emergency():
    adapter = RecordingAdapter()
    service = make_service(adapter)
    meta = {"patient": {"hn": "09900001"}, "vitals": dict(_BP)}
    await _push(service, meta, severity_level="emergency", department_code="emergency")
    assert meta["his_prescreen"]["his_department"].startswith("แผนก ER")


async def test_failed_push_records_failed_status():
    adapter = RecordingAdapter(ok=False)
    service = make_service(adapter)
    meta = {"patient": {"hn": "09900001"}, "vitals": dict(_BP)}
    await _push(service, meta)
    assert meta["his_prescreen"]["status"] == "failed"


async def test_push_exception_never_raises():
    class Boom(RecordingAdapter):
        async def push_prescreen(self, prescreen):
            raise RuntimeError("HIS down")

    service = make_service(Boom())
    meta = {"patient": {"hn": "09900001"}, "vitals": dict(_BP)}
    await _push(service, meta)  # must not raise
    assert meta["his_prescreen"]["status"] == "failed"
