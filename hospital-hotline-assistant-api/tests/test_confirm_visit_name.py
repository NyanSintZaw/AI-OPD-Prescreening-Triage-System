"""Confirm-visit-name decision helpers (no live DB)."""

from app.services.screening.nlu_yesno import classify_yes_no
from app.schemas import ConfirmVisitNameRequest, ConfirmVisitNameResponse


def test_confirm_request_accepts_button_or_text():
    assert ConfirmVisitNameRequest(confirmed=True).confirmed is True
    assert ConfirmVisitNameRequest(text="ใช่ค่ะ").text == "ใช่ค่ะ"


def test_confirm_response_shape():
    out = ConfirmVisitNameResponse(
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
        "visit": {"visit_id": "990000000000000002", "patient_name": "สมหญิง รักษาดี"},
        "patient_history": {"is_first_time": False, "chronic_conditions": "diabetes"},
        "vitals": {"weight_kg": 65.0, "height_cm": 158.0, "source": "his_recent"},
    })
    out = await apply_confirm_decision(conn, "s-1", "no")
    assert out.unlinked is True
    assert "visit" not in conn.metadata
    assert "patient_history" not in conn.metadata
    assert "vitals" not in conn.metadata


async def test_reject_keeps_real_measurements():
    # A cuff/manual reading measured at the booth belongs to the person
    # standing there — unlinking the (wrong) record must not discard it.
    from app.services.visit_confirm import apply_confirm_decision

    conn = _MetaConn({
        "visit": {"visit_id": "990000000000000002", "patient_name": "X"},
        "vitals": {"systolic": 132, "diastolic": 84, "source": "device"},
    })
    await apply_confirm_decision(conn, "s-1", "no")
    assert conn.metadata["vitals"]["systolic"] == 132
