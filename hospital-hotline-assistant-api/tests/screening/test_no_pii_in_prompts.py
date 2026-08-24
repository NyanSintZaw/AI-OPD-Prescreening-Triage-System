"""No patient identifier may reach the model.

The engine is heading for a model hosted on a workstation inside the
hospital, reconnected to on every turn. Whatever we put in a prompt crosses
a process boundary and lands in that server's logs, so the rule is simple:
identifiers we hold — name, HN, VN, slip code, session id, birthdate — are
never sent. The rules engine decides with them; the model never sees them.

This test builds every prompt the engine can produce, using a state stuffed
with unmistakable identifiers, and fails if any of them appear. It is a
guard, not a demonstration: a new prompt that interpolates
``state.patient_name`` fails here rather than in production.

The patient's own utterance is the one thing we cannot filter — they may say
their name out loud. That is why the model is hosted locally; see
docs/ai-model-io.md.
"""

from __future__ import annotations

import pytest

from app.services.screening.extraction import build_extraction_prompt
from app.services.screening.nlu_backstop import _PROMPTS
from app.services.screening.nodes.explain import _EXPLAIN_PROMPT, _NAME_LINE
from app.services.screening.nodes.question import _PARAPHRASE_PROMPT, _REPHRASE_INSTRUCTION
from app.services.screening.persistence import load_seed_criteria
from app.services.screening.persona import persona_block
from app.services.screening.state import ScreeningState

# Distinctive on purpose: a substring check must not match ordinary Thai or
# English prose in a prompt template.
NAME_TH = "สมชายทดสอบนามสกุลยาว"
IDENTIFIERS = {
    "patient_name_th": NAME_TH,
    "patient_name_en": "Somchai Testlongsurname",
    "hn": "09900001",
    "visit_id": "990000000000000001",
    "slip_code": "MCH-A1B2-C3D4",
    "session_id": "1f0b8c2e-4a77-4d1e-9d3a-2b6e5c7f81aa",
    "birthdate": "1968-03-14",
}


def _loaded_state(language: str) -> ScreeningState:
    state = ScreeningState(session_id=IDENTIFIERS["session_id"], language=language)
    state.patient_name = NAME_TH
    state.chief_complaint = "แน่นหน้าอกมา 2 ชั่วโมง"
    state.age_years = 58
    state.vitals = {"systolic": 158, "diastolic": 94}
    return state


def _assert_clean(prompt: str, where: str) -> None:
    leaked = [k for k, v in IDENTIFIERS.items() if v in prompt]
    assert not leaked, f"{where} leaks {leaked} to the model:\n{prompt}"


@pytest.mark.parametrize("language", ["th", "en"])
def test_extraction_prompt_carries_no_identifier(language):
    state = _loaded_state(language)
    prompt = build_extraction_prompt(
        load_seed_criteria(), state, "ผมเจ็บหน้าอก", "คุณมีอาการเจ็บหน้าอกหรือไม่",
    )
    _assert_clean(prompt, "extraction")


@pytest.mark.parametrize("language", ["th", "en"])
def test_explain_prompt_carries_no_identifier(language):
    """The greeting survives as a placeholder — the name is substituted into
    the finished reply, after the model has answered."""
    prompt = _EXPLAIN_PROMPT[language].format(
        persona=persona_block(language),
        summary="แน่นหน้าอกมา 2 ชั่วโมง",
        department="แผนก OPD MED (อายุรกรรม)",
        name_line=_NAME_LINE[language],
        urgency_line="",
        reference="",
        closing_line="",
    )
    _assert_clean(prompt, "explain")
    assert "[NAME]" in prompt, "the greeting must still be asked for"


@pytest.mark.parametrize("language", ["th", "en"])
def test_paraphrase_prompt_carries_no_identifier(language):
    prompt = _PARAPHRASE_PROMPT[language].format(
        persona=persona_block(language),
        # The recent exchange is symptom speech — it must never carry a name
        # or number either (the identity gate takes no name at all).
        recent="ผู้ป่วย: แน่นหน้าอกมา 2 ชั่วโมง",
        context="แน่นหน้าอกมา 2 ชั่วโมง",
        known="อายุ 58 ปี",
        instruction=_REPHRASE_INSTRUCTION[language],
        question="อาการเจ็บหน้าอกร้าวไปที่แขนหรือไม่",
    )
    _assert_clean(prompt, "paraphrase")


@pytest.mark.parametrize("kind", sorted(_PROMPTS))
def test_gate_templates_hardcode_no_identifier(kind):
    """``context`` is a real slot — the resume gate fills it with a status —
    so this checks the template itself, with the value a caller actually
    passes. What a caller may put in the slot is the next test."""
    prompt = _PROMPTS[kind].format(
        utterance="ใช่ครับ", language="th", context="in_progress",
    )
    _assert_clean(prompt, f"gate:{kind}")


def test_identity_gate_asks_without_the_name():
    """It used to read "You are <name>, is that correct?". The name added
    nothing — the reply confirms or denies on its own."""
    prompt = _PROMPTS["identity_yesno"]
    assert "{context}" not in prompt


def test_no_call_site_passes_an_identifier_as_gate_context():
    """The template being clean is not enough: ``context`` is interpolated
    verbatim, so a caller handing it ``patient_name`` would leak just the
    same. This scans every module that reaches the gate."""
    import inspect

    from app.routers import sessions
    from app.services.screening import voice_bridge
    from app.services.screening.nodes import followup

    banned = ("patient_name", "\"hn\"", "'hn'", "visit_id", "slip_code", "birthdate")
    for module in (sessions, voice_bridge, followup):
        for line in inspect.getsource(module).splitlines():
            if "context=" not in line:
                continue
            hit = [b for b in banned if b in line]
            assert not hit, f"{module.__name__} passes {hit} as gate context: {line}"


@pytest.mark.parametrize("language", ["th", "en"])
def test_recent_turns_mask_our_own_use_of_the_name(language):
    """The assistant's own lines (greeting, explain after [NAME] substitution,
    follow-up ack) carry the real name; recent_turns feeds them back into the
    question prompt. engine._remember is the one choke point — it must mask."""
    from app.services.screening.engine import _remember
    from app.services.screening.nodes.question import recent_exchange_lines
    from app.services.screening import templates

    state = _loaded_state(language)
    polite = templates.polite_name(NAME_TH, language)
    _remember(state, "assistant", f"สวัสดีค่ะ {polite} วันนี้เป็นอะไรมาคะ")
    _remember(state, "assistant", f"{NAME_TH} คะ ไปที่แผนก OPD ได้เลยค่ะ")
    _remember(state, "user", "แน่นหน้าอกมา 2 ชั่วโมง")
    recent = recent_exchange_lines(state, language)
    prompt = _PARAPHRASE_PROMPT[language].format(
        persona=persona_block(language), recent=recent,
        context="แน่นหน้าอกมา 2 ชั่วโมง", known="",
        instruction=_REPHRASE_INSTRUCTION[language],
        question="อาการเจ็บหน้าอกร้าวไปที่แขนหรือไม่",
    )
    _assert_clean(prompt, "paraphrase+recent_turns")
    assert "[NAME]" in recent


@pytest.mark.parametrize("language", ["th", "en"])
def test_surveillance_prompt_carries_no_identifier(language):
    from app.services.surveillance_extractor import (
        _EXTRACTION_PROMPT, screening_summary_text,
    )

    state = _loaded_state(language)
    prompt = _EXTRACTION_PROMPT.format(messages=screening_summary_text(state))
    _assert_clean(prompt, "surveillance")


def test_openai_compatible_requires_a_local_base_url():
    """Unset base URL must fail at startup — never drift to api.openai.com."""
    from types import SimpleNamespace

    from app.services.screening.model_adapter import build_chat_model

    settings = SimpleNamespace(
        screening_model_provider="openai_compatible", screening_model_name="qwen",
        screening_openai_base_url=None, screening_openai_api_key=None,
    )
    with pytest.raises(ValueError, match="SCREENING_OPENAI_BASE_URL"):
        build_chat_model(settings)
    settings.screening_openai_base_url = "http://192.168.10.5:8000/v1"
    model = build_chat_model(settings)
    assert "192.168.10.5" in str(model.openai_api_base)
