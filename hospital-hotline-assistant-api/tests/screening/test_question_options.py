"""Question node: LLM-phrased questions with generated quick-reply options.

The structured paraphrase returns question + 3–4 tappable answers; bad options
(validator leaks, over-long, fewer than 2) fall back to deterministic chips,
and the prompt carries what the patient already answered so nothing is re-asked.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.screening.nodes.base import GraphDeps
from app.services.screening.nodes.question import (
    PhrasedQuestion,
    known_answers_line,
    make_question_node,
)
from app.services.screening.rules.criteria_models import parse_criteria
from app.services.screening.state import Finding, ScreeningState

from .fakes import FakeChatModel

CRITERIA_PATH = (
    Path(__file__).resolve().parents[2] / "app" / "data" / "screening_criteria_v1.json"
)


@pytest.fixture(scope="module")
def criteria():
    return parse_criteria(json.loads(CRITERIA_PATH.read_text()))


def _state(**kwargs) -> ScreeningState:
    defaults = dict(
        session_id="q-opts",
        language="en",
        phase="history",
        complaint_category="nose_throat",
        chief_complaint="sore throat",
        age_years=33.0,
        # resolve red flags + BP so the next unresolved question is nt_onset
        # (BP is always asked now — no age gate — so seed a measured reading)
        vitals={"sbp": 118.0, "dbp": 76.0},
        findings={
            "dyspnea": Finding(state="absent"),
            "severe_respiratory_distress": Finding(state="absent"),
            "neck_swelling_dysphagia": Finding(state="absent"),
            "epistaxis_uncontrolled": Finding(state="absent"),
        },
    )
    defaults.update(kwargs)
    return ScreeningState(**defaults)


def _deps(model) -> GraphDeps:
    return GraphDeps(model=model, question_budget=8)


async def _run(model, state, criteria):
    node = make_question_node(_deps(model))
    return await node({"s": state, "criteria": criteria, "audit": []})


async def test_llm_options_attached_to_paraphrase(criteria):
    model = FakeChatModel()
    model.phrasings.append(PhrasedQuestion(
        question="When did your sore throat start?",
        options=["Today", "2–3 days ago", "About a week", "Longer"],
    ))
    result = await _run(model, _state(), criteria)
    out = result["output"]
    assert out.reply == "When did your sore throat start?"
    assert [o["label"] for o in out.reply_options] == [
        "Today", "2–3 days ago", "About a week", "Longer",
    ]


async def test_bad_options_fall_back_to_authored_chips(criteria):
    model = FakeChatModel()
    model.phrasings.append(PhrasedQuestion(
        question="When did it start?",
        # validator leak ("level 2") must poison nothing but the options
        options=["Today", "You are triage level 2"],
    ))
    result = await _run(model, _state(), criteria)
    out = result["output"]
    assert out.reply == "When did it start?"
    # nt_onset has authored options in the criteria — used as fallback
    labels = [o["label"] for o in out.reply_options]
    assert "Today" in labels and len(labels) >= 3
    assert all("level" not in label.lower() for label in labels)


async def test_paraphrase_failure_keeps_verbatim_and_chips(criteria):
    model = FakeChatModel()  # empty queues -> structured call raises
    result = await _run(model, _state(), criteria)
    out = result["output"]
    assert out.reply  # verbatim template text
    assert out.reply_options  # deterministic chips still offered


async def test_prompt_carries_known_answers(criteria):
    model = FakeChatModel()
    model.phrasings.append(PhrasedQuestion(question="And how long has it lasted?"))
    state = _state(slots={"onset": "2–3 days ago"})
    await _run(model, state, criteria)
    assert "onset: 2–3 days ago" in model.prompts[-1]


def test_known_answers_line_summarizes_slots_and_findings():
    state = _state(slots={"onset": "yesterday", "severity": "4/10"})
    line = known_answers_line(state)
    assert "onset: yesterday" in line and "severity: 4/10" in line
    assert "reported:" not in line  # only absent findings on this state
    state.findings["fever"] = Finding(state="present")
    assert "fever" in known_answers_line(state)


async def test_multi_finding_red_flag_gets_per_finding_chips(criteria):
    """Compound red flags must offer one chip per finding + 'None of these' —
    a bare Yes was unmappable and undertriaged a meningitis-sign answer."""
    from app.services.screening.nodes.question import localize_options
    from app.services.screening.rules.question_policy import get_template

    fever = get_template(criteria, "fever")
    fv_danger = next(q for q in fever.questions if q.id == "fv_danger")
    chips = localize_options(fv_danger, "en", criteria)
    ids = [c["id"] for c in chips]
    assert ids[:-1] == fv_danger.finding_ids
    assert ids[-1] == "none_of_these"
    labels_th = [c["label"] for c in localize_options(fv_danger, "th", criteria)]
    assert labels_th[-1] == "ไม่มีอาการเหล่านี้"

    # single-finding red flags keep plain Yes/No
    fv_chemo = next(q for q in fever.questions if q.id == "fv_chemo")
    assert [c["id"] for c in localize_options(fv_chemo, "en", criteria)] == ["yes", "no"]


def test_unanswered_red_flag_reasked_once(criteria):
    from app.services.screening.rules.question_policy import (
        InterviewInputs,
        next_question,
    )

    def inputs(asked, counts):
        return InterviewInputs(
            complaint_category="headache",
            findings={"dyspnea": "absent", "severe_respiratory_distress": "absent"},
            answered_slots=frozenset(),
            asked_question_ids=frozenset(asked),
            age_known=True,
            age_years=70.0,
            measured_vitals=frozenset({"sbp"}),
            questions_asked=len(asked),
            question_budget=8,
            ask_counts=counts,
        )

    # asked once, still unanswered -> asked again
    q = next_question(criteria, inputs(["hd_befast"], {"hd_befast": 1}))
    assert q is not None and q.id == "hd_befast"
    # asked twice unanswered -> give up, move on
    q2 = next_question(criteria, inputs(["hd_befast"], {"hd_befast": 2}))
    assert q2 is not None and q2.id != "hd_befast"
    # answered -> resolved regardless of count
    answered = InterviewInputs(
        complaint_category="headache",
        findings={
            "dyspnea": "absent", "severe_respiratory_distress": "absent",
            "facial_droop": "absent", "limb_weakness": "absent",
            "slurred_speech": "absent", "sudden_vision_loss": "absent",
            "balance_loss": "absent",
        },
        answered_slots=frozenset(),
        asked_question_ids=frozenset(["hd_befast"]),
        age_known=True,
        age_years=70.0,
        measured_vitals=frozenset({"sbp"}),
        questions_asked=1,
        question_budget=8,
        ask_counts={"hd_befast": 1},
    )
    q3 = next_question(criteria, answered)
    assert q3 is None or q3.id != "hd_befast"
