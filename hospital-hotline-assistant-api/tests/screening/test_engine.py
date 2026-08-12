"""Engine + graph tests with a fake model: golden conversation scenarios."""

import pytest

from app.services.screening.engine import ScreeningTriageEngine
from app.services.screening.extraction import ExtractionResult, FindingUpdate
from app.services.screening.persistence import InMemoryStateStore

from .fakes import FakeChatModel


def make_engine(criteria, model=None):
    return ScreeningTriageEngine(
        model=model,
        store=InMemoryStateStore(criteria),
        question_budget=8,
        model_label="screening:test",
    )


def ext(**kwargs):
    updates = [
        FindingUpdate(id=fid, state=state)
        for fid, state in kwargs.pop("findings", {}).items()
    ]
    return ExtractionResult(finding_updates=updates, **kwargs)


async def test_emergency_confirmed_before_firing(criteria):
    """Chest pain + sweating from free text: the tuple only fires after the
    patient confirms the extracted findings (confirm-before-fire) — an
    emergency is never declared from inferred words alone."""

    model = FakeChatModel()
    model.extractions.append(ext(
        chief_complaint="chest pain and sweating",
        complaint_category="chest_pain",
        findings={"chest_pain": "present", "diaphoresis": "present"},
    ))
    engine = make_engine(criteria, model)

    result = await engine.run_turn(
        session_id="s1", language="en", input_mode="text",
        content="I have chest pain and I'm sweating a lot",
    )
    # Turn 1: no disposition — a verbatim confirm question instead.
    assert not result["classification"].get("classified")
    assert result["reply"]  # the confirm question text

    # Confirm both driving findings (chip-style yes answers).
    model.extractions.append(ext(findings={"chest_pain": "present"}))
    result = await engine.run_turn(
        session_id="s1", language="en", input_mode="button", content="Yes",
    )
    assert not result["classification"].get("classified")
    model.extractions.append(ext(findings={"diaphoresis": "present"}))
    result = await engine.run_turn(
        session_id="s1", language="en", input_mode="button", content="Yes",
    )

    classification = result["classification"]
    assert classification["classified"] is True
    assert classification["level"] == 2
    assert classification["department_code"] == "emergency"
    assert "tt_chest_pain_diaphoresis" in classification["red_flags"]
    # patient-facing reply: directs to ER, never mentions the level
    assert "Emergency" in result["reply"]
    assert "level" not in result["reply"].lower()
    assert result["model_name"] == "screening:test"


async def test_emergency_fires_immediately_from_measured_vitals(criteria):
    """Objective inputs need no confirmation: a cuff crisis reading disposes
    on the same turn it arrives."""

    model = FakeChatModel()
    model.extractions.append(ext(
        chief_complaint="dizzy",
        complaint_category="headache",
        findings={"headache": "present"},
    ))
    engine = make_engine(criteria, model)
    result = await engine.run_turn(
        session_id="s-vitals", language="en", input_mode="text",
        content="I feel dizzy",
        turn_context={"age_years": 50, "vitals": {"sbp": 200, "dbp": 122}},
    )
    classification = result["classification"]
    assert classification.get("classified") is True
    assert classification["level"] == 2
    assert "dv_adult_bp_crisis" in classification["red_flags"]


async def test_cough_interview_loop_to_general_opd(criteria):
    """Simple cough: structured interview -> level 4 -> opd_general."""

    model = FakeChatModel()
    engine = make_engine(criteria, model)
    session = "s2"

    async def turn(text, extraction=None, turn_context=None):
        if extraction is not None:
            model.extractions.append(extraction)
        return await engine.run_turn(
            session_id=session,
            language="en",
            input_mode="text",
            content=text,
            turn_context=turn_context,
        )

    # T1: chief complaint -> engine asks for age first
    r = await turn("I have a cough", ext(
        chief_complaint="cough", complaint_category="dyspnea_cough",
        findings={"cough": "present"},
    ))
    assert r["classification"] == {}
    assert "old" in r["reply"].lower()  # age question

    # T2: age -> universal breathing question
    r = await turn("I'm 30", ext(age_years=30))
    assert "breath" in r["reply"].lower() or "trouble" in r["reply"].lower()
    assert r["classification"] == {}

    # T3: no breathing trouble -> template red flags in priority order
    r = await turn("no", ext(findings={
        "dyspnea": "absent", "severe_respiratory_distress": "absent",
    }))
    assert r["classification"] == {}  # dc_severe_distress next

    # T4..: deny remaining red flags, then temp + BP + onset + weight
    r = await turn("no, I can speak fine", ext(findings={
        "severe_respiratory_distress": "absent", "blue_lips": "absent",
    }))
    r = await turn("no blood", ext(findings={"hemoptysis": "absent"}))
    r = await turn("no chest pain", ext(findings={"chest_pain": "absent"}))
    r = await turn("no fever", ext(findings={"fever": "absent", "high_fever": "absent"}))
    assert r["classification"] == {}
    # temp is a standard booth vital in every template (MFU manual: all
    # outpatients), requested even after a fever denial, before BP.
    assert r.get("awaiting_measurement") == "temp"
    # ext(): the real model returns an (empty) extraction for a bare number;
    # leaving the fake queue empty would look like two consecutive LLM
    # failures across the temp+BP turns and escalate to a nurse.
    r = await turn("36.7", ext(), turn_context={"vitals": {"temp": 36.7}})
    assert r.get("awaiting_measurement") == "sbp"
    r = await turn("BP 118/76", turn_context={"vitals": {"sbp": 118, "dbp": 76}})
    r = await turn("it started 3 days ago", ext(slot_updates={"onset": "3 days ago"}))
    r = await turn(
        "68 kg, 172 cm",
        turn_context={"vitals": {"weight": 68, "height": 172}},
    )

    assert r["classification"].get("classified") is True
    assert r["classification"]["level"] == 4
    assert r["classification"]["department_code"] == "opd_general"
    assert "OPD General" in r["reply"]
    assert "level" not in r["reply"].lower()


async def test_thai_tinnitus_meets_ent_criteria(criteria):
    """Thai session: tinnitus meets ENT acceptance -> opd_ent, Thai replies."""

    model = FakeChatModel()
    engine = make_engine(criteria, model)
    session = "s3"

    model.extractions.append(ext(
        chief_complaint="มีเสียงดังในหู", complaint_category="ear",
        findings={"tinnitus": "present"}, age_years=45,
    ))
    r = await engine.run_turn(
        session_id=session, language="th", input_mode="text",
        content="มีเสียงวิ้ง ๆ ในหูค่ะ อายุ 45 ปี",
    )
    # Thai question from the template
    assert any("฀" <= ch <= "๿" for ch in r["reply"])

    answers = [
        ext(findings={"dyspnea": "absent", "severe_respiratory_distress": "absent"}),
        ext(findings={"facial_droop": "absent"}),
        ext(findings={"foreign_body_ent_24h": "absent"}),
        ext(slot_updates={"severity": "2"}, pain_score=2),
        ext(slot_updates={"onset": "สัปดาห์ก่อน"}),
        ext(slot_updates={"duration": "1 สัปดาห์"}),
        ext(findings={"hearing_loss": "absent", "ear_discharge": "absent", "vertigo_positional": "absent"}),
    ]
    r_final = None
    for extraction in answers:
        model.extractions.append(extraction)
        r_final = await engine.run_turn(
            session_id=session, language="th", input_mode="text", content="ตอบคำถามค่ะ",
        )
        if r_final["classification"].get("classified"):
            break

    if r_final is None or not r_final["classification"].get("classified"):
        r_final = await engine.run_turn(
            session_id=session,
            language="th",
            input_mode="text",
            content="68 กก. 165 ซม.",
            turn_context={"vitals": {"weight": 68, "height": 165}},
        )

    classification = r_final["classification"]
    assert classification["classified"] is True
    assert classification["department_code"] == "opd_ent"
    assert classification["level"] in (3, 4)
    # Thai reply, no level disclosure
    assert any("฀" <= ch <= "๿" for ch in r_final["reply"])
    assert "ระดับ" not in r_final["reply"]


async def test_extraction_failure_escalates_to_nurse(criteria):
    model = FakeChatModel()  # empty queues -> every extraction raises
    engine = make_engine(criteria, model)
    r1 = await engine.run_turn(
        session_id="s6", language="en", input_mode="text", content="hello",
    )
    r2 = await engine.run_turn(
        session_id="s6", language="en", input_mode="text", content="hello again",
    )
    assert r2["escalated"] is True
    assert "nurse" in r2["reply"].lower()
    assert r2["classification"] == {}


async def test_no_model_escalates(criteria):
    engine = make_engine(criteria, model=None)
    r = await engine.run_turn(
        session_id="s7", language="th", input_mode="text", content="ปวดท้อง",
    )
    assert r["escalated"] is True


async def test_stream_event_sequence(criteria):
    model = FakeChatModel()
    model.extractions.append(ext(
        chief_complaint="dizzy", complaint_category="headache",
        findings={"headache": "present"},
    ))
    engine = make_engine(criteria, model)
    events = []
    # Measured crisis vitals dispose without confirmation (objective input).
    async for event in engine.run_turn_stream(
        session_id="s8", language="en", input_mode="text", content="I feel dizzy",
        turn_context={"age_years": 50, "vitals": {"sbp": 200, "dbp": 122}},
    ):
        events.append(event)
    types = [e["type"] for e in events]
    assert types == ["delta", "classified", "done"]
    assert events[-1]["reply"] == events[0]["text"]
    assert events[-1]["classification"]["classified"] is True


async def test_repeat_guidance_after_done(criteria):
    model = FakeChatModel()
    engine = make_engine(criteria, model)
    session = "s9"
    model.extractions.append(ext(
        chief_complaint="dizzy", complaint_category="headache",
        findings={"headache": "present"},
    ))
    await engine.run_turn(
        session_id=session, language="en", input_mode="text", content="hi",
        turn_context={"age_years": 50, "vitals": {"sbp": 200, "dbp": 122}},
    )
    # a later plain turn repeats guidance instead of restarting the interview
    r = await engine.run_turn(
        session_id=session, language="en", input_mode="text", content="so where do I go?",
    )
    assert "proceed to" in r["reply"].lower()
    assert r["classification"] == {}


async def test_decision_from_classification_mapping(criteria):
    engine = make_engine(criteria)
    decision = engine.decision_from_classification(
        {"level": 2, "department_code": "emergency", "key_reason": "x"}
    )
    assert decision.severity_level == "emergency"
    assert engine.decision_from_classification({"level": 4}).severity_level == "general"
    assert engine.decision_from_classification({"level": 3}).severity_level == "urgent"


async def test_question_paraphrase_validated_falls_back(criteria):
    """A paraphrase that leaks the level is rejected -> verbatim template."""

    model = FakeChatModel()
    engine = make_engine(criteria, model)
    model.extractions.append(ext(
        chief_complaint="stomach ache", complaint_category="abdominal_pain",
        findings={"abdominal_pain": "present"}, age_years=30,
    ))
    # first question after ingest is a red flag (verbatim, no LLM call);
    # queue a poisoned paraphrase for when a slot question comes up
    model.text_replies.append("You are triage level 5 so tell me when it started")
    r = await engine.run_turn(
        session_id="s10", language="en", input_mode="text", content="stomach ache",
    )
    assert "level" not in r["reply"].lower()


# ── Impossible values: re-ask once, then continue without the vital ───────

async def test_impossible_spoken_temperature_is_reasked_then_skipped(criteria):
    """A patient who reports 50 °C is told what's wrong and asked again; a
    second impossible answer leaves the vital missing rather than looping."""
    model = FakeChatModel()
    # Turn 1: fever reported with the red flags cleared → temperature is the
    # next thing the interview needs.
    model.extractions.append(ext(
        chief_complaint="fever",
        complaint_category="fever",
        findings={
            "fever": "present", "confusion": "absent", "dyspnea": "absent",
            "severe_respiratory_distress": "absent", "stiff_neck": "absent",
            "recent_chemotherapy": "absent", "rash_vesicles": "absent",
            "palm_sole_rash": "absent",
        },
    ))
    # Turns 2 and 3: impossible temperatures.
    model.extractions.append(ext(temperature_c=50))
    model.extractions.append(ext(temperature_c=50))
    engine = make_engine(criteria, model)

    first = await engine.run_turn(
        session_id="s1", language="en", input_mode="text",
        content="I have a fever",
        turn_context={"age_years": 30, "gender": "female"},
    )
    assert first["awaiting_measurement"] == "temp"

    second = await engine.run_turn(
        session_id="s1", language="en", input_mode="text", content="50",
    )
    # The refusal is explained in the reply, and the reading is asked for again.
    assert second["awaiting_measurement"] == "temp"
    assert "30" in second["reply"] and "45" in second["reply"]

    third = await engine.run_turn(
        session_id="s1", language="en", input_mode="text", content="50 again",
    )
    # Given up on: the interview moves on rather than asking a third time.
    assert third["awaiting_measurement"] != "temp"

    state = await engine._store.load("s1")
    assert "temp" not in state.vitals, "an impossible temp must never be stored"
    assert state.rejected_vitals["temp"]["value"] == 50
    assert state.rejected_vitals["temp"]["attempts"] == 2


async def test_impossible_cuff_reading_never_reaches_the_rules(criteria):
    """turn_context is filtered before the red-flag gate: 300/220 must not
    dispose an emergency the way a real 250/130 would."""
    model = FakeChatModel()
    model.extractions.append(ext(
        chief_complaint="headache", complaint_category="headache",
    ))
    engine = make_engine(criteria, model)

    result = await engine.run_turn(
        session_id="s1", language="en", input_mode="text",
        content="my head hurts",
        turn_context={"age_years": 40, "vitals": {"systolic": 300, "diastolic": 220}},
    )
    assert "dv_adult_bp_crisis" not in result["classification"].get("red_flags", [])

    state = await engine._store.load("s1")
    assert "sbp" not in state.vitals and "dbp" not in state.vitals
    assert state.rejected_vitals["dbp"]["source"] == "measured"


async def test_real_crisis_cuff_reading_still_disposes(criteria):
    """Control for the test above — the filter must not swallow real crises."""
    model = FakeChatModel()
    model.extractions.append(ext(
        chief_complaint="headache", complaint_category="headache",
    ))
    engine = make_engine(criteria, model)

    result = await engine.run_turn(
        session_id="s2", language="en", input_mode="text",
        content="my head hurts",
        turn_context={"age_years": 40, "vitals": {"systolic": 250, "diastolic": 130}},
    )
    assert "dv_adult_bp_crisis" in result["classification"]["red_flags"]
    assert result["classification"]["department_code"] == "emergency"
