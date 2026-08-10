"""HIS patient name flows through the whole session, not just the greeting.

The name arrives at link-visit (sessions.metadata->visit->patient_name),
rides turn_context into engine state, and later mentions — the disposition
explanation (fallback + LLM prompt) and the follow-up close/ack — address the
patient by their DB name in both languages instead of a generic phrase.
"""

from __future__ import annotations

import pytest

from app.services.screening import templates
from app.services.screening.engine import ScreeningTriageEngine
from app.services.screening.nodes.base import GraphDeps
from app.services.screening.nodes.explain import fallback_explanation
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


def _explain_deps(model) -> GraphDeps:
    """Same departments as _deps(), but with a model so the node really calls it."""
    deps = _deps()
    return GraphDeps(
        model=model,
        question_budget=deps.question_budget,
        department_names=deps.department_names,
        validator_department_names=deps.validator_department_names,
    )


def test_polite_name_forms():
    assert templates.polite_name("สมชาย ใจดี", "th") == "คุณสมชาย"
    assert templates.polite_name("Waraporn Srisuk", "en") == "Waraporn"
    assert templates.polite_name("  ", "en") is None
    assert templates.polite_name(None, "th") is None


def test_turn_context_carries_patient_name():
    state = ScreeningState(session_id="s", language="th")
    ScreeningTriageEngine._apply_turn_context(
        state, {"patient_name": "สมชาย ใจดี", "age_years": 41}
    )
    assert state.patient_name == "สมชาย ใจดี"
    # a later turn without the name (e.g. context rebuilt) must not erase it
    ScreeningTriageEngine._apply_turn_context(state, {"vitals": {"temp": 36.5}})
    assert state.patient_name == "สมชาย ใจดี"


def test_fallback_explanation_addresses_by_name():
    for lang, name, expected in (
        ("en", "Waraporn Srisuk", "Waraporn"),
        ("th", "สมชาย ใจดี", "คุณสมชาย"),
    ):
        state = ScreeningState(
            session_id="s", language=lang, patient_name=name,
            classification={"classified": True, "level": 5, "department_code": "opd_general"},
        )
        reply = fallback_explanation(state, _deps())
        assert expected in reply, reply
    # anonymous walk-in stays generic
    state = ScreeningState(
        session_id="s", language="en",
        classification={"classified": True, "level": 5, "department_code": "opd_general"},
    )
    assert fallback_explanation(state, _deps()) == templates.OPD_EXPLAIN["en"].format(
        department="OPD General Practice"
    )


@pytest.mark.parametrize("lang,name,decline,expected", [
    ("en", "Waraporn Srisuk", "No, that's all, thank you", "Waraporn"),
    ("th", "สมชาย ใจดี", "ไม่มีแล้วค่ะ ขอบคุณค่ะ", "คุณสมชาย"),
])
async def test_followup_close_addresses_by_name(lang, name, decline, expected):
    state = ScreeningState(
        session_id="fu", language=lang, phase="follow_up", patient_name=name,
        classification={"classified": True, "level": 4, "department_code": "opd_general"},
    )
    node = make_followup_node(_deps())
    result = await node({"s": state, "user_text": decline, "criteria": None, "audit": []})
    out = result["output"]
    assert result["s"].phase == "done"
    assert expected in out.reply, out.reply
    assert result["s"].patient_follow_up is None


async def test_followup_ack_addresses_by_name():
    state = ScreeningState(
        session_id="fu", language="th", phase="follow_up", patient_name="สมชาย ใจดี",
        classification={"classified": True, "level": 4, "department_code": "opd_general"},
    )
    node = make_followup_node(_deps())
    result = await node({
        "s": state, "user_text": "ฝากบอกคุณหมอว่าแพ้ยาเพนิซิลลินครับ",
        "criteria": None, "audit": [],
    })
    assert "คุณสมชาย" in result["output"].reply
    assert result["s"].patient_follow_up == "ฝากบอกคุณหมอว่าแพ้ยาเพนิซิลลินครับ"


async def test_name_is_substituted_after_the_model_answers():
    """The greeting survives, the name never goes on the wire.

    The model is asked for a `[NAME]` token and the real name is put in
    afterwards, so the patient still hears "คุณสมชาย" while the prompt — and
    therefore the model server's logs — carry no identifier.
    """
    from app.services.screening.nodes.explain import make_explain_node

    from .fakes import FakeChatModel

    model = FakeChatModel()
    model.text_replies.append("[NAME] คะ ขอให้ไปที่ OPD เวชปฏิบัติทั่วไป นะคะ")
    state = ScreeningState(
        session_id="name-sub",
        language="th",  # type: ignore[arg-type]
        phase="disposed",  # type: ignore[arg-type]
        classification={
            "classified": True,
            "level": 4,
            "department_code": "opd_general",
            "symptoms_summary": "ไข้สองวัน",
        },
    )
    state.patient_name = "สมชาย ใจดี"

    result = await make_explain_node(_explain_deps(model))(
        {"s": state, "user_text": "", "criteria": None, "audit": []}
    )
    reply = result["output"].reply

    assert "สมชาย" not in model.prompts[0]
    assert "[NAME]" in model.prompts[0]
    assert "คุณสมชาย" in reply
    assert "[NAME]" not in reply


async def test_stray_placeholder_never_reaches_a_patient_without_a_name():
    """No name on file -> the token is dropped, not shown."""
    from app.services.screening.nodes.explain import make_explain_node

    from .fakes import FakeChatModel

    model = FakeChatModel()
    model.text_replies.append("[NAME] ขอให้ไปที่ OPD เวชปฏิบัติทั่วไป นะคะ")
    state = ScreeningState(
        session_id="name-none",
        language="th",  # type: ignore[arg-type]
        phase="disposed",  # type: ignore[arg-type]
        classification={
            "classified": True,
            "level": 4,
            "department_code": "opd_general",
            "symptoms_summary": "ไข้สองวัน",
        },
    )

    result = await make_explain_node(_explain_deps(model))(
        {"s": state, "user_text": "", "criteria": None, "audit": []}
    )
    assert "[NAME]" not in result["output"].reply
