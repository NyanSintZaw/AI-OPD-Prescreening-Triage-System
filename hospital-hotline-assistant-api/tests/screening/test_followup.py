"""Follow-up node keyword matcher tests."""

from __future__ import annotations

import pytest

from app.services.screening.nodes.base import GraphDeps
from app.services.screening.nodes.followup import make_followup_node
from app.services.screening.state import ScreeningState


def _deps() -> GraphDeps:
    return GraphDeps(
        model=None,
        question_budget=8,
        department_names={
            "opd_general": {"en": "OPD General Practice", "th": "OPD เวชปฏิบัติทั่วไป"},
        },
        validator_department_names={"opd_general": ["OPD General Practice"]},
    )


async def _run(language: str, utterance: str, phase: str = "follow_up"):
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
    node = make_followup_node(_deps())
    result = await node({"s": state, "user_text": utterance, "criteria": None, "audit": []})
    return result["s"], result["output"]


@pytest.mark.parametrize("text", [
    "no", "nothing", "No thanks", "ไม่", "ไม่มี", "ไม่ค่ะ",
    # multi-token declines must NOT be recorded as notes
    "No, nothing else", "No, that's all. Thanks!", "I'm fine, thank you",
    "ไม่มีค่ะ", "ไม่มีค่ะ ขอบคุณค่ะ", "ไม่มีอะไรจะถามแล้วค่ะ", "แค่นี้ค่ะ",
    # "แล้ว/เลย" riders (observed live: this exact decline was written to HIS)
    "ไม่มีแล้วค่ะ ขอบคุณค่ะ", "ไม่มีแล้วครับ", "ไม่มีเลยค่ะ", "ไม่เป็นไรแล้วค่ะ",
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
