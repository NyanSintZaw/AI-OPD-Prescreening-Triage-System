"""Confirm-before-fire + evidence-quote rails.

The invariant under test: a level-1/2 disposition is never produced by
free-text extraction alone. It fires only from findings the patient confirmed
(chip/verbatim answer), the HIS record, or instrument readings — and a wrong
extraction is corrected by a single "no" instead of a false Red banner.
"""

from app.services.screening.engine import ScreeningTriageEngine
from app.services.screening.extraction import ExtractionResult, FindingUpdate
from app.services.screening.persistence import InMemoryStateStore

from .fakes import FakeChatModel


def make_engine(criteria, model):
    return ScreeningTriageEngine(
        model=model, store=InMemoryStateStore(criteria),
        question_budget=8, model_label="screening:test",
    )


def ext(**kwargs):
    updates = [
        FindingUpdate(id=fid, state=state, evidence=evidence)
        for fid, (state, evidence) in kwargs.pop("findings_ev", {}).items()
    ] + [
        FindingUpdate(id=fid, state=state)
        for fid, state in kwargs.pop("findings", {}).items()
    ]
    return ExtractionResult(finding_updates=updates, **kwargs)


async def test_overmatched_shock_finding_is_denied_not_red(criteria):
    """The live E2 bug: 'sweating' over-matched the level-1 shock-skin
    finding. The gate must ask, and one 'no' must kill the false Red."""

    model = FakeChatModel()
    model.extractions.append(ext(
        chief_complaint="แน่นหน้าอก เหงื่อแตก",
        complaint_category="chest_pain",
        findings={"chest_pain": "present", "pale_cold_sweaty": "present"},
    ))
    engine = make_engine(criteria, model)
    r = await engine.run_turn(
        session_id="g1", language="th", input_mode="text",
        content="แน่นหน้าอกนิดหน่อย เหงื่อแตกครับ",
    )
    assert not r["classification"].get("classified")  # no Red from inference

    # The confirm question is answered "no" — extraction corrected.
    model.extractions.append(ext(findings={"pale_cold_sweaty": "absent"}))
    r = await engine.run_turn(
        session_id="g1", language="th", input_mode="button", content="ไม่ใช่",
    )
    state = await engine._store.load("g1")
    assert state.findings["pale_cold_sweaty"].state == "absent"
    assert not r["classification"].get("classified")
    assert state.phase == "history"  # interview continues normally


async def test_two_non_answers_accept_the_extraction_fail_safe(criteria):
    """A patient who never clarifies must not block a potential emergency:
    after two unanswered confirm asks the extraction is accepted and the
    rule fires (over-triage is the safe failure direction)."""

    model = FakeChatModel()
    model.extractions.append(ext(
        chief_complaint="เวียนหัว เป็นลม",
        complaint_category="generic",
        findings={"syncope_24h": "present"},  # med_syncope_24h -> L2
    ))
    engine = make_engine(criteria, model)
    await engine.run_turn(
        session_id="g2", language="th", input_mode="text",
        content="เมื่อเช้าเป็นลมหมดสติไปแป๊บนึงครับ",
    )
    # Two garbled answers: extraction yields nothing either time.
    model.extractions.append(ExtractionResult())
    await engine.run_turn(
        session_id="g2", language="th", input_mode="text", content="อือ...",
    )
    model.extractions.append(ExtractionResult())
    r = await engine.run_turn(
        session_id="g2", language="th", input_mode="text", content="ฮะ?",
    )
    assert r["classification"].get("classified") is True
    assert r["classification"]["level"] <= 2


async def test_history_risk_factor_needs_no_confirm_but_spoken_finding_does(criteria):
    """E5 shape: hypertension_history is stamped from the HIS record
    (confirmed by construction); the spoken pregnancy is extraction-sourced,
    so exactly ONE confirm stands between the utterance and the emergency."""

    model = FakeChatModel()
    model.extractions.append(ext(
        chief_complaint="pregnant with a bad headache",
        complaint_category="pregnancy",
        findings={"pregnancy": "present", "headache": "present"},
    ))
    engine = make_engine(criteria, model)
    r = await engine.run_turn(
        session_id="g3", language="en", input_mode="text",
        content="I'm seven months pregnant and my head hurts badly",
        turn_context={
            "age_years": 33,
            "patient_history": {"chronic_conditions": "hypertension since 2023"},
        },
    )
    assert not r["classification"].get("classified")

    model.extractions.append(ext(findings={"pregnancy": "present"}))
    r = await engine.run_turn(
        session_id="g3", language="en", input_mode="button", content="Yes",
    )
    assert r["classification"].get("classified") is True
    assert r["classification"]["level"] == 2
    assert "tt_pregnancy_hypertension" in r["classification"]["red_flags"]


async def test_evidence_quotes_are_verified_and_stored(criteria):
    model = FakeChatModel()
    model.extractions.append(ext(
        chief_complaint="fever",
        complaint_category="fever",
        findings_ev={
            "fever": ("present", "I have a fever"),          # real quote
            "cough": ("present", "coughing all night"),      # fabricated
        },
    ))
    engine = make_engine(criteria, model)
    await engine.run_turn(
        session_id="g4", language="en", input_mode="text",
        content="I have a fever since yesterday",
    )
    state = await engine._store.load("g4")
    assert state.findings["fever"].evidence == "I have a fever"
    assert state.findings["fever"].evidence_verified is True
    assert state.findings["cough"].evidence_verified is False
    # Neither is confirmed — both came from free text, not from a question.
    assert not state.findings["fever"].confirmed
