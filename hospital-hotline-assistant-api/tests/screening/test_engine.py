"""Engine + graph tests with a fake model: golden conversation scenarios."""

import pytest

from app.services.screening.engine import ScreeningTriageEngine
from app.services.screening.extraction import ContactAnswer, ExtractionResult, FindingUpdate
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


async def test_emergency_first_turn_no_interview(criteria):
    """Chest pain + sweating -> level 2 emergency on the very first turn."""

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
    classification = result["classification"]
    assert classification["classified"] is True
    assert classification["level"] == 2
    assert classification["department_code"] == "emergency"
    assert "tt_chest_pain_diaphoresis" in classification["red_flags"]
    # patient-facing reply: directs to ER, never mentions the level
    assert "Emergency" in result["reply"]
    assert "level" not in result["reply"].lower()
    assert result["model_name"] == "screening:test"


async def test_cough_interview_loop_to_general_opd(criteria):
    """Simple cough: structured interview -> level 4 -> opd_general."""

    model = FakeChatModel()
    engine = make_engine(criteria, model)
    session = "s2"

    async def turn(text, extraction=None):
        if extraction is not None:
            model.extractions.append(extraction)
        return await engine.run_turn(
            session_id=session, language="en", input_mode="text", content=text,
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

    # T4..: deny remaining red flags, then slots
    r = await turn("no, I can speak fine", ext(findings={
        "severe_respiratory_distress": "absent", "blue_lips": "absent",
    }))
    r = await turn("no blood", ext(findings={"hemoptysis": "absent"}))
    r = await turn("no chest pain", ext(findings={"chest_pain": "absent"}))
    r = await turn("no fever", ext(findings={"fever": "absent", "high_fever": "absent"}))
    assert r["classification"] == {}
    r = await turn("about a 2", ext(distress_score=2))
    r = await turn("it started 3 days ago", ext(slot_updates={"onset": "3 days ago"}))

    # budget (8) is now spent -> dispose
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

    classification = r_final["classification"]
    assert classification["classified"] is True
    assert classification["department_code"] == "opd_ent"
    assert classification["level"] in (3, 4)
    # Thai reply, no level disclosure
    assert any("฀" <= ch <= "๿" for ch in r_final["reply"])
    assert "ระดับ" not in r_final["reply"]


async def test_contact_flow_yes_then_phone(criteria):
    model = FakeChatModel()
    engine = make_engine(criteria, model)
    session = "s4"

    # dispose first
    model.extractions.append(ext(
        chief_complaint="chest pain", complaint_category="chest_pain",
        findings={"chest_pain": "present", "diaphoresis": "present"},
    ))
    await engine.run_turn(
        session_id=session, language="en", input_mode="text", content="chest pain sweating",
    )

    # contact turn 1: yes -> ask phone
    model.contact_answers.append(ContactAnswer(requested=True))
    r = await engine.run_turn(
        session_id=session, language="en", input_mode="text",
        content="[PHASE: contact_preference]\n[CONTACT_FLOW: awaiting_consent]\nyes please",
    )
    assert r["contact"]["requested"] is True
    assert r["contact"]["needs_followup"] is True
    assert "phone" in r["reply"].lower()

    # contact turn 2: phone number -> confirmed, done
    model.contact_answers.append(ContactAnswer(requested=True, phone_number="0812345678"))
    r = await engine.run_turn(
        session_id=session, language="en", input_mode="text",
        content="[PHASE: contact_preference]\n[CONTACT_FLOW: awaiting_phone]\n0812345678",
    )
    assert r["contact"]["needs_followup"] is False
    assert r["contact"]["phone_number"] == "0812345678"
    assert "contact you" in r["reply"]


async def test_contact_decline_thai(criteria):
    model = FakeChatModel()
    engine = make_engine(criteria, model)
    session = "s5"
    model.extractions.append(ext(
        chief_complaint="ปวดหัว", complaint_category="headache",
        findings={"headache": "present", "headache_sudden_severe": "present"},
    ))
    await engine.run_turn(
        session_id=session, language="th", input_mode="text",
        content="ปวดหัวรุนแรงมากฉับพลัน",
    )
    model.contact_answers.append(ContactAnswer(requested=False))
    r = await engine.run_turn(
        session_id=session, language="th", input_mode="text",
        content="[PHASE: contact_preference]\nไม่ต้องค่ะ",
    )
    assert r["contact"]["requested"] is False
    assert r["contact"]["needs_followup"] is False
    assert any("฀" <= ch <= "๿" for ch in r["reply"])


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
        chief_complaint="chest pain", complaint_category="chest_pain",
        findings={"chest_pain": "present", "diaphoresis": "present"},
    ))
    engine = make_engine(criteria, model)
    events = []
    async for event in engine.run_turn_stream(
        session_id="s8", language="en", input_mode="text", content="chest pain, sweating",
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
        chief_complaint="cough", complaint_category="dyspnea_cough",
        findings={"chest_pain": "present", "diaphoresis": "present"},
    ))
    await engine.run_turn(session_id=session, language="en", input_mode="text", content="hi")
    model.contact_answers.append(ContactAnswer(requested=False))
    await engine.run_turn(
        session_id=session, language="en", input_mode="text",
        content="[PHASE: contact_preference]\nno",
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
