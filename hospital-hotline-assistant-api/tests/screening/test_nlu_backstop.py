"""confirm_gate — the LLM backstop behind the regex flow gates."""

from __future__ import annotations

import asyncio

import pytest

from app.services.screening import nlu_backstop
from app.services.screening.nlu_backstop import confirm_gate

from .fakes import FakeChatModel


async def test_followup_decline_verdict_with_audit_metadata():
    model = FakeChatModel()
    model.structured.append("decline")
    verdict = await confirm_gate(
        model, "followup_decline", "no worries, I'm all set", "en"
    )
    assert verdict == "decline"
    assert verdict.ok is True
    assert verdict.latency_ms >= 0
    assert verdict.raw == "decline"
    # The utterance made it into the classification prompt.
    assert "no worries" in model.prompts[-1]


async def test_identity_and_resume_kinds_use_their_own_verdicts():
    model = FakeChatModel()
    model.structured.append("yes")
    assert await confirm_gate(model, "identity_yesno", "ใช่ค่ะ ฉันเองนะ", "th") == "yes"
    model.structured.append("continue")
    assert (
        await confirm_gate(model, "resume_choice", "เอาอันเดิมต่อได้ไหม", "th")
        == "continue"
    )


async def test_model_failure_returns_unclear():
    model = FakeChatModel()  # empty structured queue → the fake raises
    verdict = await confirm_gate(model, "followup_decline", "hmm", "en")
    assert verdict == "unclear"
    assert verdict.ok is False


async def test_invalid_verdict_returns_unclear():
    model = FakeChatModel()
    model.structured.append("banana")  # fails the Literal constraint
    assert await confirm_gate(model, "identity_yesno", "yes-ish", "en") == "unclear"


async def test_no_model_or_empty_utterance_returns_unclear():
    model = FakeChatModel()
    assert await confirm_gate(None, "followup_decline", "anything", "en") == "unclear"
    assert await confirm_gate(model, "followup_decline", "   ", "en") == "unclear"
    assert model.prompts == []  # never called


async def test_timeout_returns_unclear(monkeypatch):
    class SlowStructured:
        async def ainvoke(self, prompt):
            await asyncio.sleep(1.0)

    class SlowModel:
        def with_structured_output(self, schema):
            return SlowStructured()

    monkeypatch.setattr(nlu_backstop, "BACKSTOP_TIMEOUT_S", 0.01)
    verdict = await confirm_gate(SlowModel(), "resume_choice", "umm", "en")
    assert verdict == "unclear"
    assert verdict.ok is False
