"""The screening engine is the sole authority in _finalize_chat_turn.

There is no legacy keyword rule engine any more: an interview turn (empty
classification) must stay in_progress with no department; a disposed turn
persists exactly the engine's severity + department.
"""

import time

from app.services.ai.triage_models import TriageDecision
from app.services.triage_service import TriageService


class FakeConn:
    async def fetchrow(self, query, *args):
        return {"id": "gen-id"}

    async def fetchval(self, query, *args):
        return None

    async def fetch(self, query, *args):
        return []

    async def execute(self, query, *args):
        return "OK"


_SEV = {1: "emergency", 2: "emergency", 3: "urgent", 4: "general", 5: "general"}


class FakeEngine:
    """Maps a classification dict to a decision the way the real engine does."""

    def decision_from_classification(self, classification):
        classified = bool(classification.get("classified"))
        level = classification.get("level")
        return TriageDecision(
            esi_level=level if classified else None,
            severity_level=_SEV.get(level, "unknown") if classified else "unknown",
            opd_department_code=classification.get("department_code") if classified else None,
            key_reason="reason",
            symptoms_summary="cough",
            needs_emergency_contact=False,
            classification=classification,
        )


def make_ctx():
    return {
        "msg_user": {"id": "u1"},
        "prior_metadata": {},
        "prior_classification": {},
        "department_by_code": {
            "opd_general": {"id": "d1", "kind": "opd"},
            "emergency": {"id": "e1", "kind": "emergency"},
        },
        "department_name_by_id": {"d1": "OPD General", "e1": "ER"},
        "assistant_message_override": {"id": "m1", "content": "reply"},
    }


async def _finalize(classification):
    svc = TriageService(triage_engine=FakeEngine())
    result, _ = await svc._finalize_chat_turn(
        connection=FakeConn(),
        session_id="00000000-0000-0000-0000-000000000001",
        language="en",
        content="I have a cough for three days",
        start=time.perf_counter(),
        ctx=make_ctx(),
        adk_result={"reply": "…", "classification": classification, "contact": {}},
    )
    return result


async def test_interview_turn_stays_in_progress():
    """No classification yet → severity unknown, no department assigned."""
    result = await _finalize({})
    assert result.severity_level == "unknown"
    assert result.department_id is None


async def test_disposed_turn_persists_engine_department():
    """A disposition routes exactly to the engine's department code."""
    result = await _finalize({"classified": True, "level": 4, "department_code": "opd_general"})
    assert result.severity_level == "general"
    assert result.department_id == "d1"


async def test_emergency_forces_emergency_department():
    result = await _finalize({"classified": True, "level": 1, "department_code": "opd_general"})
    assert result.severity_level == "emergency"
    assert result.department_id == "e1"  # coerced to the emergency department
