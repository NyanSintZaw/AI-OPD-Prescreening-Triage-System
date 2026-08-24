"""Confirm-patient-name decision helpers (no live DB)."""

from app.services.screening.nlu_yesno import classify_yes_no
from app.schemas import ConfirmPatientNameRequest, ConfirmPatientNameResponse


def test_confirm_request_accepts_button_or_text():
    assert ConfirmPatientNameRequest(confirmed=True).confirmed is True
    assert ConfirmPatientNameRequest(text="ใช่ค่ะ").text == "ใช่ค่ะ"


def test_confirm_response_shape():
    out = ConfirmPatientNameResponse(
        decision="no",
        name_confirmed=False,
        unlinked=True,
        patient_name="Somchai",
    )
    assert out.unlinked is True
    assert out.decision == "no"


def test_button_semantics_match_classifier():
    # Document the API contract: confirmed=True/False maps to yes/no without
    # running the classifier; free text uses classify_yes_no.
    assert classify_yes_no("yes") == "yes"
    assert classify_yes_no("no") == "no"


class _MetaConn:
    def __init__(self, metadata):
        self.metadata = dict(metadata)

    async def fetchrow(self, sql, *args):
        return {"metadata": dict(self.metadata)}

    async def execute(self, sql, *args):
        self.metadata = dict(args[1])


async def test_reject_strips_wrong_patients_his_prefill():
    # Live E2E finding (July 22): rejecting the name left the WRONG patient's
    # HIS weight/height + history on the session, which then leaked onto the
    # re-linked (correct) patient.
    from app.services.visit_confirm import apply_confirm_decision

    conn = _MetaConn({
        "patient": {"hn": "09900002", "patient_name": "สมหญิง รักษาดี"},
        "patient_history": {"is_first_time": False, "chronic_conditions": "diabetes"},
        "vitals": {"weight_kg": 65.0, "height_cm": 158.0, "source": "his_recent"},
    })
    out = await apply_confirm_decision(conn, "s-1", "no")
    assert out.unlinked is True
    assert "patient" not in conn.metadata
    assert "patient_history" not in conn.metadata
    assert "vitals" not in conn.metadata


async def test_reject_keeps_real_measurements():
    # A cuff/manual reading measured at the booth belongs to the person
    # standing there — unlinking the (wrong) record must not discard it.
    from app.services.visit_confirm import apply_confirm_decision

    conn = _MetaConn({
        "patient": {"hn": "09900002", "patient_name": "X"},
        "vitals": {"systolic": 132, "diastolic": 84, "source": "device"},
    })
    await apply_confirm_decision(conn, "s-1", "no")
    assert conn.metadata["vitals"]["systolic"] == 132


# ── REST endpoint fail-closed retry gate (parity with the voice path) ────────

import pytest
from fastapi import HTTPException


def _linked_meta(**extra):
    return {
        "patient": {"hn": "09900001", "patient_name": "สมชาย ใจดี"},
        **extra,
    }


async def _call(conn, **payload_kwargs):
    from app.routers.sessions import confirm_patient_name
    from app.schemas import ConfirmPatientNameRequest

    return await confirm_patient_name(
        "11111111-1111-1111-1111-111111111111",  # type: ignore[arg-type]
        ConfirmPatientNameRequest(**payload_kwargs),
        conn,
    )


async def test_unclear_returns_422_and_counts_attempt():
    conn = _MetaConn(_linked_meta())
    with pytest.raises(HTTPException) as exc:
        await _call(conn, text="ไม่แน่ใจ")
    assert exc.value.status_code == 422
    assert exc.value.detail == {"code": "unclear", "retries_left": 1}
    assert conn.metadata["confirm_name_attempts"] == 1
    assert "patient" in conn.metadata  # link untouched while retrying


async def test_unclear_at_retry_cap_rejects_fail_closed():
    # One unclear answer already recorded → the next one exhausts the cap and
    # is treated as an explicit "no": unlink + counter reset.
    conn = _MetaConn(_linked_meta(confirm_name_attempts=1))
    out = await _call(conn, text="ไม่แน่ใจ")
    assert out.decision == "no"
    assert out.unlinked is True
    assert out.name_confirmed is False
    assert "patient" not in conn.metadata
    assert "confirm_name_attempts" not in conn.metadata


async def test_definitive_yes_after_unclear_resets_counter():
    conn = _MetaConn(_linked_meta(confirm_name_attempts=1))
    out = await _call(conn, confirmed=True)
    assert out.decision == "yes"
    assert out.name_confirmed is True
    assert conn.metadata["patient"]["name_confirmed"] is True
    assert "confirm_name_attempts" not in conn.metadata


# ── LLM backstop before the 422 retry path ───────────────────────────────────


class _FakeStructured:
    def __init__(self, verdict):
        self._verdict = verdict

    async def ainvoke(self, prompt):
        if self._verdict is None:
            raise RuntimeError("backstop model down")
        return self._schema(verdict=self._verdict)


class _FakeModel:
    """Minimal with_structured_output surface for confirm_gate."""

    def __init__(self, verdict: str | None):
        self._verdict = verdict

    def with_structured_output(self, schema):
        s = _FakeStructured(self._verdict)
        s._schema = schema
        return s


async def test_unclear_backstop_no_rejects_immediately(monkeypatch):
    import app.routers.sessions as main_mod

    monkeypatch.setattr(main_mod, "_screening_model", lambda: _FakeModel("no"))
    conn = _MetaConn(_linked_meta())
    out = await _call(conn, text="banana banana")
    assert out.decision == "no"
    assert out.unlinked is True
    assert "patient" not in conn.metadata
    # No retry counter left behind — the answer was definitive.
    assert "confirm_name_attempts" not in conn.metadata


async def test_unclear_backstop_yes_confirms_and_resets_counter(monkeypatch):
    import app.routers.sessions as main_mod

    monkeypatch.setattr(main_mod, "_screening_model", lambda: _FakeModel("yes"))
    conn = _MetaConn(_linked_meta(confirm_name_attempts=1))
    out = await _call(conn, text="banana banana")
    assert out.decision == "yes"
    assert out.name_confirmed is True
    assert conn.metadata["patient"]["name_confirmed"] is True
    assert "confirm_name_attempts" not in conn.metadata


async def test_unclear_backstop_failure_keeps_422_flow(monkeypatch):
    import app.routers.sessions as main_mod

    monkeypatch.setattr(main_mod, "_screening_model", lambda: _FakeModel(None))
    conn = _MetaConn(_linked_meta())
    with pytest.raises(HTTPException) as exc:
        await _call(conn, text="banana banana")
    assert exc.value.status_code == 422
    assert exc.value.detail == {"code": "unclear", "retries_left": 1}
    assert conn.metadata["confirm_name_attempts"] == 1
