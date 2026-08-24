"""Question node: acknowledgement + question rendering.

Every question now goes through one render call. The model may add a short
acknowledgement of what the patient just said and (since 2026-08-23) reword
any question except a measurement request — but a red-flag / scale / confirm
rewording is used only when ``wording_violations`` is empty: it must still
name every symptom the template names, keep the 0–10 scale and ask exactly
one question. Otherwise the nurse-approved text goes out verbatim, and the
audit says why.
"""

from __future__ import annotations

import pytest

from app.services.screening.nodes.base import GraphDeps
from app.services.screening.nodes.question import (
    PhrasedQuestion,
    clean_ack,
    make_question_node,
    recent_exchange_lines,
)
from app.services.screening.rules.criteria_store import load_seed_criteria
from app.services.screening.state import RECENT_TURNS_MAX, Finding, ScreeningState

from .fakes import FakeChatModel


@pytest.fixture(scope="module")
def criteria():
    return load_seed_criteria()


def _deps(model) -> GraphDeps:
    return GraphDeps(model=model, question_budget=8)


async def _run(model, state, criteria):
    node = make_question_node(_deps(model))
    return await node({"s": state, "criteria": criteria, "audit": []})


def _fever_state(**kw) -> ScreeningState:
    """fever template, red flags unresolved → next question is fv_danger
    (red_flag, verbatim kind)."""
    defaults = dict(
        session_id="ack", language="en", phase="history",
        complaint_category="fever", chief_complaint="fever for two days",
        age_years=40.0, gender="male",
        findings={
            "dyspnea": Finding(state="absent"),
            "severe_respiratory_distress": Finding(state="absent"),
        },
        recent_turns=[
            {"role": "assistant", "text": "How old are you?"},
            {"role": "patient", "text": "I've had a fever for two days"},
        ],
    )
    defaults.update(kw)
    return ScreeningState(**defaults)


def _verbatim(criteria, qid: str, language: str = "en") -> str:
    for tpl in criteria.complaint_templates:
        for q in tpl.questions:
            if q.id == qid:
                return q.text_en if language == "en" else q.text_th
    raise KeyError(qid)


# ── a rewording that loses a symptom is refused; the template goes out ──────


async def test_red_flag_rewording_that_drops_symptoms_falls_back_to_verbatim(criteria):
    model = FakeChatModel()
    model.phrasings.append(PhrasedQuestion(
        ack="I'm sorry you've been feeling unwell.",
        # names none of confusion / breathing / stiff neck — refused
        question="Do you have any of those danger signs?",
        options=["Yes", "No"],
    ))
    result = await _run(model, _fever_state(), criteria)
    out = result["output"]
    expected = _verbatim(criteria, "fv_danger")
    assert out.reply == f"I'm sorry you've been feeling unwell. {expected}"
    assert result["audit"][-1]["ack_used"] is True
    assert result["audit"][-1]["paraphrased"] is False
    assert set(result["audit"][-1]["paraphrase_rejected"]) >= {
        "missing:confusion", "missing:stiff_neck",
    }
    # the red flag keeps its authored chips (one per finding + none), never
    # the model's free-text options
    labels = [o["label"] for o in out.reply_options]
    assert "Yes" not in labels and "No" not in labels[:1]
    assert out.reply_options[-1]["id"] == "none_of_these"


async def test_empty_ack_yields_exactly_the_verbatim_question(criteria):
    model = FakeChatModel()
    model.phrasings.append(PhrasedQuestion(ack="", question="whatever", options=[]))
    result = await _run(model, _fever_state(), criteria)
    assert result["output"].reply == _verbatim(criteria, "fv_danger")  # no leading space
    assert result["audit"][-1]["ack_used"] is False


async def test_render_failure_falls_back_to_verbatim(criteria):
    model = FakeChatModel()  # nothing queued → the structured call raises
    result = await _run(model, _fever_state(), criteria)
    assert result["output"].reply == _verbatim(criteria, "fv_danger")
    assert result["audit"][-1]["ok"] is False


# ── the acknowledgement guard ────────────────────────────────────────────────


@pytest.mark.parametrize("bad", [
    "Two days of fever — is it getting worse?",      # smuggled question
    "มีไข้มาสองวันแล้วนะคะ ยังมีไข้อยู่ไหม",             # Thai question particle
    "x" * 120,                                        # too long
    "I understand, that sounds like level 3 urgency.",  # validator leak
    "   ",
])
def test_clean_ack_drops_unsafe_acknowledgements(bad):
    assert clean_ack(bad, "th" if "ไหม" in bad else "en") == ""


def test_clean_ack_keeps_a_short_plain_clause():
    assert clean_ack(" I'm sorry to hear that. ", "en") == "I'm sorry to hear that."
    assert clean_ack("เข้าใจค่ะ มีไข้มาสองวันแล้ว", "th") == "เข้าใจค่ะ มีไข้มาสองวันแล้ว"


async def test_leaky_ack_is_dropped_but_question_still_goes_out(criteria):
    model = FakeChatModel()
    model.phrasings.append(PhrasedQuestion(
        ack="Noted, that sounds like level 3.", question="x", options=[],
    ))
    result = await _run(model, _fever_state(), criteria)
    assert result["output"].reply == _verbatim(criteria, "fv_danger")
    assert result["audit"][-1]["ack_used"] is False


# ── recent exchange plumbing ─────────────────────────────────────────────────


def test_recent_exchange_lines_labels_roles_per_language():
    state = _fever_state()
    assert recent_exchange_lines(state, "en") == (
        "You: How old are you?\nPatient: I've had a fever for two days"
    )
    assert recent_exchange_lines(state, "th").startswith("คุณ: ")
    assert recent_exchange_lines(ScreeningState(session_id="x"), "en") == "-"


async def test_prompt_carries_the_recent_exchange(criteria):
    model = FakeChatModel()
    model.phrasings.append(PhrasedQuestion(question="x"))
    await _run(model, _fever_state(), criteria)
    assert "I've had a fever for two days" in model.prompts[0]
    # A red flag is reworded too (2026-08-23), with the symptom words the
    # meaning check will look for handed to the model.
    assert "Keep every one of these symptoms" in model.prompts[0]
    assert "confusion" in model.prompts[0] and "stiff neck" in model.prompts[0]


def test_recent_turns_is_capped_by_the_engine_helper():
    from app.services.screening.engine import _remember

    state = ScreeningState(session_id="cap")
    for i in range(6):
        _remember(state, "patient" if i % 2 == 0 else "assistant", f"line {i}")
    assert len(state.recent_turns) == RECENT_TURNS_MAX
    assert state.recent_turns[0]["text"] == "line 2"
    assert {t["role"] for t in state.recent_turns} == {"patient", "assistant"}
    _remember(state, "assistant", "   ")  # blank lines are not remembered
    assert len(state.recent_turns) == RECENT_TURNS_MAX


# ── meaning-checked rewording of red flags / scales / confirms (2026-08-23) ──


async def test_faithful_red_flag_rewording_is_used_and_chips_stay_by_finding(criteria):
    model = FakeChatModel()
    model.phrasings.append(PhrasedQuestion(
        ack="Okay.",
        question="With the fever, have you felt confused, short of breath, or noticed a stiff neck?",
        options=["Yes", "No", "Not sure"],  # must be ignored — chips carry finding ids
    ))
    result = await _run(model, _fever_state(), criteria)
    out = result["output"]
    assert out.reply == (
        "Okay. With the fever, have you felt confused, short of breath, or noticed a stiff neck?"
    )
    assert result["audit"][-1]["paraphrased"] is True
    assert "paraphrase_rejected" not in result["audit"][-1]
    assert [o["id"] for o in out.reply_options] == [
        "confusion", "dyspnea", "stiff_neck", "none_of_these",
    ]


async def test_rewording_missing_one_symptom_of_a_compound_red_flag_is_refused(criteria):
    model = FakeChatModel()
    model.phrasings.append(PhrasedQuestion(
        ack="", question="Have you felt confused or short of breath with the fever?", options=[],
    ))
    result = await _run(model, _fever_state(), criteria)
    assert result["output"].reply == _verbatim(criteria, "fv_danger")
    assert result["audit"][-1]["paraphrase_rejected"] == ["missing:stiff_neck"]


async def test_rewording_with_two_questions_is_refused(criteria):
    model = FakeChatModel()
    model.phrasings.append(PhrasedQuestion(
        ack="",
        question="Any confusion or a stiff neck? And is breathing hard?",
        options=[],
    ))
    result = await _run(model, _fever_state(), criteria)
    assert result["output"].reply == _verbatim(criteria, "fv_danger")
    assert "question_count" in result["audit"][-1]["paraphrase_rejected"]


async def test_thai_red_flag_rewording_checked_against_thai_terms(criteria):
    state = _fever_state(language="th", chief_complaint="มีไข้มาสองวัน", recent_turns=[])
    model = FakeChatModel()
    model.phrasings.append(PhrasedQuestion(
        ack="ค่ะ",
        question="ช่วงที่มีไข้ มีอาการซึมสับสน หายใจเหนื่อย หรือคอแข็งบ้างไหมคะ",
        options=[],
    ))
    result = await _run(model, state, criteria)
    assert result["audit"][-1]["paraphrased"] is True
    assert result["output"].reply.startswith("ค่ะ ช่วงที่มีไข้")

    model = FakeChatModel()
    model.phrasings.append(PhrasedQuestion(
        ack="", question="มีอาการอื่นร่วมกับไข้ไหมคะ", options=[],
    ))
    result = await _run(model, state, criteria)
    assert result["output"].reply == _verbatim(criteria, "fv_danger", "th")
    assert "missing:confusion" in result["audit"][-1]["paraphrase_rejected"]


def _abdominal_scale_state() -> ScreeningState:
    return _fever_state(
        complaint_category="abdominal_pain", chief_complaint="stomach pain",
        findings={
            "dyspnea": Finding(state="absent"),
            "severe_respiratory_distress": Finding(state="absent"),
            "abdominal_pain": Finding(state="present"),
            "hematemesis": Finding(state="absent"),
            "bloody_stool": Finding(state="absent"),
            "melena": Finding(state="absent"),
        },
        asked_question_ids=["ap_gi_bleed"],
    )


async def test_scale_rewording_must_keep_0_to_10(criteria):
    state = _abdominal_scale_state()
    model = FakeChatModel()
    model.phrasings.append(PhrasedQuestion(ack="", question="How bad is the pain right now?", options=[]))
    result = await _run(model, state, criteria)
    assert result["output"].reply == _verbatim(criteria, "ap_severity")
    assert "missing:scale_0_10" in result["audit"][-1]["paraphrase_rejected"]
    assert [o["id"] for o in result["output"].reply_options] == [str(i) for i in range(11)]

    model = FakeChatModel()
    model.phrasings.append(PhrasedQuestion(
        ack="", question="If 0 is no pain and 10 is the worst imaginable, where is it now?", options=[],
    ))
    result = await _run(model, _abdominal_scale_state(), criteria)
    assert result["audit"][-1]["paraphrased"] is True


async def test_measurement_request_is_never_reworded(criteria):
    state = _fever_state(
        findings={
            "dyspnea": Finding(state="absent"),
            "severe_respiratory_distress": Finding(state="absent"),
            "fever": Finding(state="present"),
            "confusion": Finding(state="absent"),
            "stiff_neck": Finding(state="absent"),
            "recent_chemotherapy": Finding(state="absent"),
            "rash_vesicles": Finding(state="absent"),
            "palm_sole_rash": Finding(state="absent"),
        },
        asked_question_ids=["fv_danger", "fv_chemo", "fv_rash"],
    )
    model = FakeChatModel()
    model.phrasings.append(PhrasedQuestion(
        ack="Thanks.", question="Pop your finger in the thermometer for me?", options=[],
    ))
    result = await _run(model, state, criteria)
    assert result["output"].awaiting_measurement == "temp"
    assert result["output"].reply == f"Thanks. {_verbatim(criteria, 'fv_temp')}"
    assert result["audit"][-1]["paraphrased"] is False


async def test_confirm_question_rewording_must_name_the_finding(criteria):
    state = _fever_state(
        complaint_category="chest_pain", chief_complaint="chest pain",
        findings={"chest_pain": Finding(state="present"), "diaphoresis": Finding(state="present")},
        pending_confirm=["diaphoresis"],
    )
    model = FakeChatModel()
    model.phrasings.append(PhrasedQuestion(
        ack="", question="Are you sweating a lot right now, like a cold sweat?", options=["Yes", "No"],
    ))
    result = await _run(model, state, criteria)
    assert result["audit"][-1]["question_id"] == "confirm_diaphoresis"
    assert result["audit"][-1]["paraphrased"] is True
    assert [o["id"] for o in result["output"].reply_options] == ["yes", "no"]

    state.pending_confirm = ["diaphoresis"]
    model = FakeChatModel()
    model.phrasings.append(PhrasedQuestion(ack="", question="Is that still happening?", options=[]))
    result = await _run(model, state, criteria)
    assert result["audit"][-1]["paraphrased"] is False
    assert result["audit"][-1]["paraphrase_rejected"] == ["missing:diaphoresis"]
