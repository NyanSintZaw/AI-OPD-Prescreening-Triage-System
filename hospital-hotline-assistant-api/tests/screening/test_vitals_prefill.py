"""Structured vitals + age pre-fill into the deterministic engine.

Proves that booth-measured vitals (turn_context) drive the red-flag gate:
a hypertensive-crisis cuff reading fires the danger-vitals rule on turn 1
without the LLM deciding anything, and a linked visit's age suppresses the
age question and routes a child to pediatrics.
"""

from app.services.screening.engine import ScreeningTriageEngine
from app.services.screening.extraction import ExtractionResult, FindingUpdate
from app.services.screening.persistence import InMemoryStateStore
from app.services.screening.vitals import normalize_vitals

from .fakes import FakeChatModel


def make_engine(criteria, model):
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


# --- normalization -----------------------------------------------------------

def test_normalize_vitals_maps_and_derives_map():
    out = normalize_vitals({"systolic": 200, "diastolic": 120, "pulse_bpm": 96})
    assert out["sbp"] == 200
    assert out["dbp"] == 120
    assert out["hr"] == 96
    assert out["map"] == round(120 + (200 - 120) / 3, 1)


def test_normalize_vitals_drops_junk_and_empty():
    assert normalize_vitals(None) == {}
    assert normalize_vitals({"weight_kg": 70, "unknown": 1, "systolic": ""}) == {}
    assert normalize_vitals({"temperature": "38.5"}) == {"temp": 38.5}


# --- engine pre-fill ---------------------------------------------------------

async def test_cuff_reading_fires_danger_vitals_on_turn_1(criteria):
    """Adult + hypertensive-crisis cuff reading → level 2 emergency without
    any interview, decided purely from the measured vitals."""
    model = FakeChatModel()
    engine = make_engine(criteria, model)

    result = await engine.run_turn(
        session_id="v-emergency",
        language="en",
        input_mode="text",
        content="I have a bad headache",
        turn_context={
            "age_years": 55,
            "vitals": {"systolic": 200, "diastolic": 122, "pulse_bpm": 90},
        },
    )

    classification = result["classification"]
    assert classification.get("classified") is True
    assert classification["level"] <= 2
    assert classification["department_code"] == "emergency"
    # patient reply must never leak the level/color
    assert "level" not in result["reply"].lower()


async def test_linked_age_suppresses_age_question_and_routes_child(criteria):
    """An 8-year-old's age comes from the linked visit, so the engine never
    asks age and the child routing rule sends them to pediatrics."""
    model = FakeChatModel()
    engine = make_engine(criteria, model)

    async def turn(text, extraction):
        model.extractions.append(extraction)
        return await engine.run_turn(
            session_id="v-child",
            language="en",
            input_mode="text",
            content=text,
            turn_context={"age_years": 8, "vitals": {}},
        )

    r = await turn("my son has a cough", ext(
        chief_complaint="cough", complaint_category="dyspnea_cough",
        findings={"cough": "present"},
    ))
    # the engine must not have asked for age (it was pre-filled)
    assert "old" not in r["reply"].lower() or "how old" not in r["reply"].lower()

    answers = [
        ext(findings={"dyspnea": "absent", "severe_respiratory_distress": "absent"}),
        ext(findings={"severe_respiratory_distress": "absent", "blue_lips": "absent"}),
        ext(findings={"hemoptysis": "absent"}),
        ext(findings={"chest_pain": "absent"}),
        ext(findings={"fever": "absent", "high_fever": "absent"}),
        ext(distress_score=1),
        ext(slot_updates={"onset": "2 days ago"}),
        ext(slot_updates={"duration": "2 days"}),
    ]
    for extraction in answers:
        if r["classification"].get("classified"):
            break
        r = await turn("answer", extraction)

    assert r["classification"]["classified"] is True
    assert r["classification"]["department_code"] == "opd_pediatrics"
