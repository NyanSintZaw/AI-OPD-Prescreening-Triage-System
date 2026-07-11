"""Regression: the langgraph engine is authoritative in _finalize_chat_turn.

The legacy keyword routing-rule + scale overrides (the ADK path's engine)
must NOT fire under TRIAGE_ENGINE=langgraph — otherwise they assign a
department + severity on an *interview* turn, marking it complete and
auto-ending voice calls. (Found via the voice sanity check: an English
cough matched the "OPD general symptoms" routing rule mid-interview.)
"""

import time

import pytest

from app.services import triage_service as ts_mod
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


class FakeEngine:
    """Interview turn => empty classification => severity 'unknown'."""

    def decision_from_classification(self, classification):
        classified = bool(classification.get("classified"))
        return TriageDecision(
            esi_level=classification.get("level") if classified else None,
            severity_level="general" if classified else "unknown",
            opd_department_code=classification.get("department_code") if classified else None,
            key_reason=None,
            symptoms_summary="cough",
            needs_emergency_contact=False,
            classification=classification,
        )


class FakeRoutingRule:
    name = "OPD general symptoms"
    severity_override = "general"
    department_id = "d1"
    reason = "Matched routing rule: OPD general symptoms"
    confidence = 0.75
    keywords = ["cough", "cold"]


def make_ctx(routing_matches):
    return {
        "msg_user": {"id": "u1"},
        "prior_metadata": {},
        "prior_classification": {},
        "department_by_code": {
            "opd_general": {"id": "d1", "kind": "opd"},
            "emergency": {"id": "e1", "kind": "emergency"},
        },
        "department_name_by_id": {"d1": "OPD General", "e1": "ER"},
        "emergency_matches": [],
        "routing_matches": routing_matches,
        # Provide the assistant message so finalize skips the messages insert.
        "assistant_message_override": {"id": "m1", "content": "May I ask your age?"},
    }


async def _finalize(engine_flag, routing_matches, monkeypatch):
    monkeypatch.setattr(ts_mod.settings, "triage_engine", engine_flag)
    svc = TriageService(triage_engine=FakeEngine())
    result, _ = await svc._finalize_chat_turn(
        connection=FakeConn(),
        session_id="00000000-0000-0000-0000-000000000001",
        language="en",
        content="I have a cough for three days",
        start=time.perf_counter(),
        ctx=make_ctx(routing_matches),
        adk_result={"reply": "May I ask your age?", "classification": {}, "contact": {}},
    )
    return result


async def test_langgraph_interview_turn_not_completed_by_routing_rule(monkeypatch):
    """A cough matches the OPD-general routing rule, but under langgraph the
    interview turn must stay in_progress (severity unknown, no department)."""
    result = await _finalize("langgraph", [FakeRoutingRule()], monkeypatch)
    assert result.severity_level == "unknown"   # NOT 'general'
    assert result.department_id is None


async def test_adk_still_applies_routing_rule(monkeypatch):
    """The ADK path keeps its legacy rule-engine behavior unchanged."""
    result = await _finalize("adk", [FakeRoutingRule()], monkeypatch)
    assert result.severity_level == "general"
    assert result.department_id == "d1"
