"""Explain-node closing instruction: farewell only where the flow truly ends.

Non-emergency explanations are followed by the follow-up offer and the
deterministic FOLLOW_UP_CLOSE ("Take care / ดูแลตัวเองด้วยนะคะ"), so the LLM
must be told NOT to add its own farewell there (user-reported duplication).
Emergency explanations are terminal and keep the warm close.
"""

from __future__ import annotations

from app.services.screening.nodes.base import GraphDeps
from app.services.screening.nodes.explain import (
    _CLOSING_EMERGENCY,
    _CLOSING_NON_EMERGENCY,
    make_explain_node,
)
from app.services.screening.state import ScreeningState

from .fakes import FakeChatModel


def _deps(model: FakeChatModel) -> GraphDeps:
    return GraphDeps(
        model=model,
        question_budget=8,
        department_names={
            "opd_general": {"en": "OPD General Practice", "th": "OPD เวชปฏิบัติทั่วไป"},
            "emergency": {"en": "the Emergency Department", "th": "ห้องฉุกเฉิน"},
        },
        validator_department_names={
            "opd_general": ["OPD General Practice", "OPD เวชปฏิบัติทั่วไป"],
            "emergency": ["the Emergency Department", "ห้องฉุกเฉิน"],
        },
    )


async def _run(language: str, level: int) -> FakeChatModel:
    model = FakeChatModel()
    model.text_replies.append("")  # force fallback; we only inspect the prompt
    department = "emergency" if level <= 2 else "opd_general"
    state = ScreeningState(
        session_id="explain-closing",
        language=language,  # type: ignore[arg-type]
        phase="disposed",  # type: ignore[arg-type]
        classification={
            "classified": True,
            "level": level,
            "department_code": department,
            "symptoms_summary": "fever for two days",
        },
    )
    node = make_explain_node(_deps(model))
    await node({"s": state, "user_text": "", "criteria": None, "audit": []})
    return model


async def test_non_emergency_prompt_forbids_farewell():
    for language in ("en", "th"):
        model = await _run(language, level=4)
        assert model.prompts, "explain node never called the model"
        assert _CLOSING_NON_EMERGENCY[language] in model.prompts[0]
        assert _CLOSING_EMERGENCY[language] not in model.prompts[0]


async def test_emergency_prompt_keeps_warm_close():
    for language in ("en", "th"):
        model = await _run(language, level=1)
        assert model.prompts, "explain node never called the model"
        assert _CLOSING_EMERGENCY[language] in model.prompts[0]
