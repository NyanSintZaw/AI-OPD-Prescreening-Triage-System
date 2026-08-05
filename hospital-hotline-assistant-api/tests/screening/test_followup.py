"""Follow-up node keyword matcher tests."""

from __future__ import annotations

import pytest

from app.services.screening.nodes.base import GraphDeps
from app.services.screening.nodes.followup import make_followup_node
from app.services.screening.state import ScreeningState

from .fakes import FakeChatModel


def _deps(model=None) -> GraphDeps:
    return GraphDeps(
        model=model,
        question_budget=8,
        department_names={
            "opd_general": {"en": "OPD General Practice", "th": "OPD เวชปฏิบัติทั่วไป"},
        },
        validator_department_names={"opd_general": ["OPD General Practice"]},
    )


async def _run_full(language: str, utterance: str, model=None, phase: str = "follow_up"):
    state = ScreeningState(
        session_id="fu",
        language=language,  # type: ignore[arg-type]
        phase=phase,  # type: ignore[arg-type]
        classification={
            "classified": True,
            "level": 4,
            "department_code": "opd_general",
        },
    )
    node = make_followup_node(_deps(model))
    return await node(
        {"s": state, "user_text": utterance, "criteria": None, "audit": []}
    )


async def _run(language: str, utterance: str, phase: str = "follow_up"):
    result = await _run_full(language, utterance, phase=phase)
    return result["s"], result["output"]


@pytest.mark.parametrize("text", [
    "no", "nothing", "No thanks", "ไม่", "ไม่มี", "ไม่ค่ะ",
    # multi-token declines must NOT be recorded as notes
    "No, nothing else", "No, that's all. Thanks!", "I'm fine, thank you",
    "ไม่มีค่ะ", "ไม่มีค่ะ ขอบคุณค่ะ", "ไม่มีอะไรจะถามแล้วค่ะ", "แค่นี้ค่ะ",
    # "แล้ว/เลย" riders (observed live: this exact decline was written to HIS)
    "ไม่มีแล้วค่ะ ขอบคุณค่ะ", "ไม่มีแล้วครับ", "ไม่มีเลยค่ะ", "ไม่เป็นไรแล้วค่ะ",
    # observed live 2026-07-27 (VN 03): this exact decline was noted for the
    # doctor — free-phrased English declines
    "No, there isn't anything. I'm done.", "There's nothing else.",
    "I don't have anything else.", "That's it, thanks.", "Nothing to add.",
    "ไม่มีอะไรจะบอกค่ะ", "เสร็จแล้วค่ะ",
])
async def test_negative_closes(text):
    state, out = await _run("en" if text.isascii() else "th", text)
    assert state.phase == "done"
    assert out.flow_complete is True
    assert out.post_disposition is True
    assert state.patient_follow_up is None


@pytest.mark.parametrize("text", [
    "yes", "Yes", "มี", "ใช่", "ครับ",
    "Yes please", "yes, I have a question", "มีค่ะ", "มีคำถามค่ะ",
])
async def test_affirmative_prompts(text):
    lang = "en" if text.isascii() else "th"
    state, out = await _run(lang, text)
    assert state.phase == "follow_up"
    assert out.flow_complete is False
    assert out.post_disposition is True
    assert state.patient_follow_up is None


async def test_direct_note_recorded_en():
    state, out = await _run("en", "Please tell the doctor about my penicillin allergy")
    assert state.phase == "done"
    assert out.flow_complete is True
    assert state.patient_follow_up == "Please tell the doctor about my penicillin allergy"


async def test_direct_note_recorded_th():
    state, out = await _run("th", "แพ้เพนิซิลินค่ะ")
    assert state.phase == "done"
    assert state.patient_follow_up == "แพ้เพนิซิลินค่ะ"


async def test_question_content_recorded_even_with_leading_no():
    state, out = await _run("en", "No wait — can I eat before the blood test?")
    assert state.phase == "done"
    assert state.patient_follow_up == "No wait — can I eat before the blood test?"


# ── LLM backstop behind the regex gate ───────────────────────────────────────


async def test_novel_decline_rescued_by_backstop():
    model = FakeChatModel()
    model.structured.append("decline")
    result = await _run_full("en", "no worries, I'm all set", model)
    state, out = result["s"], result["output"]
    assert state.phase == "done"
    assert out.flow_complete is True
    assert state.patient_follow_up is None  # nothing pushed to HIS
    # Polite close, not the "noted for the doctor" ack.
    from app.services.screening import templates

    assert result["output"].reply == templates.follow_up_close(
        None, "OPD General Practice", "en"
    )
    # The backstop call is audited.
    entry = result["audit"][-1]
    assert entry["call_site"] == "gate_backstop"
    assert entry["kind"] == "followup_decline"
    assert entry["regex_verdict"] == "content"
    assert entry["llm_verdict"] == "decline"
    assert entry["ok"] is True


async def test_backstop_failure_stores_note_as_today():
    model = FakeChatModel()  # empty structured queue → call fails → "unclear"
    result = await _run_full("en", "no worries, I'm all set", model)
    assert result["s"].patient_follow_up == "no worries, I'm all set"
    assert result["audit"][-1]["ok"] is False
    assert result["audit"][-1]["llm_verdict"] == "unclear"


async def test_backstop_content_verdict_stores_note():
    model = FakeChatModel()
    model.structured.append("content")
    result = await _run_full("en", "please tell the doctor I take warfarin", model)
    assert result["s"].patient_follow_up == "please tell the doctor I take warfarin"


@pytest.mark.parametrize("text", [
    # Live-seen misses (2026-07-27) — now closed by the regex fast path
    # without spending an LLM call; the backstop stays behind them.
    "ไม่มีแล้วค่ะ ขอบคุณค่ะ",
    "No, there isn't anything. I'm done.",
    "no thanks",
])
async def test_regex_decline_never_calls_the_model(text):
    model = FakeChatModel()  # would raise if consulted (empty queues)
    result = await _run_full("en" if text.isascii() else "th", text, model)
    assert result["s"].patient_follow_up is None
    assert result["s"].phase == "done"
    assert model.prompts == []  # no LLM call on the deterministic path


@pytest.mark.parametrize("text", ["k", ".", "ๆ", "", "y"])
async def test_sub_two_char_scrap_never_stored(text):
    model = FakeChatModel()
    result = await _run_full("en", text, model)
    assert result["s"].patient_follow_up is None
    assert result["s"].phase == "done"
    assert result["output"].flow_complete is True
    assert model.prompts == []  # too trivial to even ask the backstop
