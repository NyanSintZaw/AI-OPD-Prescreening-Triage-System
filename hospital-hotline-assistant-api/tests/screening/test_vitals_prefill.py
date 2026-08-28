"""Structured vitals + age pre-fill into the deterministic engine.

Proves that booth-measured vitals (turn_context) drive the red-flag gate:
a hypertensive-crisis cuff reading fires the danger-vitals rule on turn 1
without the LLM deciding anything, and a linked visit's age suppresses the
age question and routes a child to pediatrics.
"""

import json

from app.services.screening.engine import ScreeningTriageEngine
from app.services.screening.extraction import ExtractionResult, FindingUpdate
from app.services.screening.persistence import InMemoryStateStore
from app.services.screening.state import ScreeningState
from app.services.screening.vitals import (
    effective_vitals,
    missing_core_vitals,
    normalize_vitals,
)

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
    assert normalize_vitals({"unknown": 1, "systolic": ""}) == {}
    assert normalize_vitals({"weight_kg": 70, "height_cm": 165}) == {
        "weight": 70.0,
        "height": 165.0,
    }
    assert normalize_vitals({"temperature": "38.5"}) == {"temp": 38.5}


def test_missing_core_vitals_kiosk_bp_and_temp():
    # Typical kiosk session: cuff (sbp/dbp) + thermometer, never hr/rr/spo2
    # from an instrument — those must surface as a nurse-review caution.
    measured = normalize_vitals({"systolic": 120, "diastolic": 80, "temperature": 36.8})
    assert missing_core_vitals(measured) == ["hr", "rr", "spo2"]


def test_missing_core_vitals_nothing_measured():
    assert missing_core_vitals({}) == ["hr", "rr", "spo2", "temp", "sbp"]
    assert missing_core_vitals(None) == ["hr", "rr", "spo2", "temp", "sbp"]


def test_missing_core_vitals_all_measured():
    measured = {"hr": 72, "rr": 16, "spo2": 98, "temp": 36.8, "sbp": 120}
    assert missing_core_vitals(measured) == []


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
            # booth vitals (BP, temp, SpO2, weight/height) already recorded, so
            # the measurement questions are pre-resolved and don't lengthen this
            # interview
            turn_context={
                "age_years": 8,
                "vitals": {
                    "weight_kg": 24, "height_cm": 128,
                    "systolic": 104, "diastolic": 66, "temperature": 36.8,
                    "spo2": 98,
                },
            },
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


# --- measured vs spoken vitals ----------------------------------------------

def test_effective_vitals_measured_wins():
    state = ScreeningState(session_id="s")
    state.vitals.update({"temp": 39.5, "hr": 80})
    state.measured_vitals["temp"] = 37.2
    assert effective_vitals(state) == {"temp": 37.2, "hr": 80}


def test_old_state_payload_defaults_measured_vitals():
    """States persisted before the measured_vitals field must deserialize."""
    payload = json.loads(ScreeningState(session_id="s-old").to_json())
    payload.pop("measured_vitals")
    restored = ScreeningState.from_json(payload)
    assert restored.measured_vitals == {}

    restored.measured_vitals["temp"] = 37.2
    assert ScreeningState.from_json(restored.to_json()).measured_vitals == {
        "temp": 37.2
    }


async def test_measured_temp_beats_spoken_temp(criteria):
    """Booth thermometer read 37.0 °C; the patient claims "38.5 at home".
    The measured value must survive — rules never see the spoken 38.5 and no
    fever finding is stamped from the claim."""
    model = FakeChatModel()
    engine = make_engine(criteria, model)
    model.extractions.append(ext(
        chief_complaint="headache",
        complaint_category="generic",
        temperature_c=38.5,
    ))

    await engine.run_turn(
        session_id="v-spoken-temp",
        language="en",
        input_mode="text",
        content="I measured 38.5 at home this morning",
        turn_context={"age_years": 30, "vitals": {"temperature": 37.0}},
    )

    state = await engine._store.load("v-spoken-temp")
    assert state is not None
    assert state.measured_vitals["temp"] == 37.0
    assert state.vitals["temp"] == 37.0  # spoken 38.5 was NOT written
    assert effective_vitals(state)["temp"] == 37.0
    fever = state.findings.get("fever")
    assert fever is None or fever.state != "present"


async def test_measured_fever_still_stamped_from_turn_context(criteria):
    """A measured 38.2 °C keeps stamping the fever finding (regression guard
    for apply_objective_findings after the effective_vitals refactor)."""
    model = FakeChatModel()
    engine = make_engine(criteria, model)
    model.extractions.append(ext(
        chief_complaint="fever", complaint_category="fever",
    ))

    await engine.run_turn(
        session_id="v-measured-fever",
        language="en",
        input_mode="text",
        content="I feel hot",
        turn_context={"age_years": 30, "vitals": {"temperature": 38.2}},
    )

    state = await engine._store.load("v-measured-fever")
    assert state is not None
    assert state.findings["fever"].state == "present"
