"""Plausibility bounds: the input filter that keeps impossible numbers out.

The load-bearing distinction under test is "impossible" vs "dangerous": a
systolic of 250 must survive the filter and fire the hypertensive-crisis rule,
while a systolic of 400 must be discarded before any rule sees it.
"""

import pytest

from app.services.screening.rules.criteria_models import (
    default_cross_checks,
    default_vital_bounds,
)
from app.services.screening.state import ScreeningState
from app.services.screening.vitals import (
    check_vitals,
    effective_vitals,
    record_rejections,
)

BOUNDS = default_vital_bounds()


@pytest.mark.parametrize("name,bound", sorted(BOUNDS.items()))
def test_edges_accepted_and_just_outside_rejected(name, bound):
    """Bounds are inclusive; a hair outside either edge is refused."""
    for value in (bound.min, bound.max):
        accepted, rejected = check_vitals({name: value})
        assert accepted.get(name) == value, f"{name}={value} should be accepted"
        assert not rejected

    for value in (bound.min - 0.1, bound.max + 0.1):
        accepted, rejected = check_vitals({name: value})
        assert name not in accepted, f"{name}={value} should be refused"
        assert [r.vital for r in rejected] == [name]
        assert rejected[0].reason == "out_of_range"
        assert rejected[0].value == value


@pytest.mark.parametrize("name,bound", sorted(BOUNDS.items()))
def test_every_bound_is_bilingual(name, bound):
    assert bound.retry_text_en.strip(), f"{name} missing English retry wording"
    assert bound.retry_text_th.strip(), f"{name} missing Thai retry wording"
    assert bound.min < bound.max


def test_cross_checks_are_bilingual():
    for check_id, check in default_cross_checks().items():
        assert check.text_en.strip(), f"{check_id} missing English wording"
        assert check.text_th.strip(), f"{check_id} missing Thai wording"


def test_critical_but_possible_reading_survives():
    """The whole point: 250/130 is a real hypertensive crisis, not garbage."""
    accepted, rejected = check_vitals({"systolic": 250, "diastolic": 130})
    assert not rejected
    assert accepted["sbp"] == 250
    assert accepted["dbp"] == 130


def test_impossible_reading_is_dropped_with_its_derived_map():
    accepted, rejected = check_vitals({"systolic": 400, "diastolic": 220})
    assert "sbp" not in accepted and "dbp" not in accepted
    # ``map`` is derived from sbp/dbp — it must not outlive them.
    assert "map" not in accepted
    assert {r.vital for r in rejected} == {"sbp", "dbp"}


def test_swapped_blood_pressure_is_rejected():
    """Both numbers are individually in range, so only the pair check catches it."""
    accepted, rejected = check_vitals({"systolic": 80, "diastolic": 120})
    assert "sbp" not in accepted and "dbp" not in accepted
    assert {r.reason for r in rejected} == {"sbp_le_dbp"}
    assert all(r.text_th for r in rejected)


def test_equal_systolic_and_diastolic_is_rejected():
    _, rejected = check_vitals({"systolic": 100, "diastolic": 100})
    assert rejected


@pytest.mark.parametrize("weight,height", [(1, 200), (400, 50)])
def test_bmi_cross_check_catches_impossible_pairs(weight, height):
    """Each number is inside its own bound; only the pair is impossible."""
    assert BOUNDS["weight"].contains(weight) and BOUNDS["height"].contains(height)
    accepted, rejected = check_vitals({"weight_kg": weight, "height_cm": height})
    assert "weight" not in accepted and "height" not in accepted
    assert {r.reason for r in rejected} == {"bmi_implausible"}


def test_height_in_metres_is_rejected():
    """The common kiosk typo: 1.7 instead of 170."""
    accepted, _ = check_vitals({"weight_kg": 70, "height_cm": 1.7})
    assert "height" not in accepted and "weight" not in accepted


def test_plausible_body_passes_bmi_check():
    accepted, rejected = check_vitals({"weight_kg": 70, "height_cm": 170})
    assert not rejected
    assert accepted["weight"] == 70 and accepted["height"] == 170


def test_unrelated_vitals_survive_a_neighbours_rejection():
    """One bad number must not discard the whole reading."""
    accepted, rejected = check_vitals({"temperature": 37.2, "pulse": 900})
    assert accepted["temp"] == 37.2
    assert [r.vital for r in rejected] == ["hr"]


def test_rejected_value_never_reaches_the_rules():
    state = ScreeningState(session_id="s1")
    accepted, rejected = check_vitals({"temperature": 50})
    state.vitals.update(accepted)
    record_rejections(state, rejected, source="reported")

    assert "temp" not in effective_vitals(state)
    assert state.rejected_vitals["temp"]["value"] == 50
    assert state.rejected_vitals["temp"]["source"] == "reported"
    assert state.rejected_vitals["temp"]["attempts"] == 1


def test_repeat_offences_are_counted():
    state = ScreeningState(session_id="s1")
    for _ in range(2):
        _, rejected = check_vitals({"temperature": 50})
        record_rejections(state, rejected, source="reported")
    assert state.rejected_vitals["temp"]["attempts"] == 2


def test_criteria_bounds_override_the_defaults(criteria):
    """A criteria document's own bounds win over the built-in defaults."""
    criteria.vital_bounds["temp"].max = 40.0
    try:
        accepted, rejected = check_vitals({"temperature": 42}, criteria)
        assert "temp" not in accepted
        assert rejected[0].text_th == criteria.vital_bounds["temp"].retry_text_th
    finally:
        criteria.vital_bounds["temp"].max = 45.0


# ── The hospital record must never receive a refused value ────────────────
#
# HIS Stage 1 publishes ``metadata["vitals"]`` verbatim
# (triage_service._maybe_push_referral). Two independent paths must therefore
# keep impossible numbers out of that dict.


@pytest.mark.parametrize(
    "payload",
    [
        {"systolic": 400, "diastolic": 120},   # impossible systolic
        {"systolic": 300, "diastolic": 220},   # impossible diastolic
        {"systolic": 80, "diastolic": 120},    # swapped
        {"systolic": 120, "diastolic": 80, "temperature_c": 50},
        {"systolic": 120, "diastolic": 80, "weight_kg": 900},
    ],
)
def test_rest_endpoint_refuses_impossible_vitals(payload):
    """The write path into session metadata (and thus into the HIS) rejects."""
    from pydantic import ValidationError

    from app.schemas import SessionVitalsUpdate

    with pytest.raises(ValidationError):
        SessionVitalsUpdate(**payload)


def test_rest_endpoint_accepts_a_real_crisis_reading():
    from app.schemas import SessionVitalsUpdate

    assert SessionVitalsUpdate(systolic=250, diastolic=130).systolic == 250


@pytest.mark.parametrize("vital,value", [("temp", 50), ("weight", 900), ("height", 5)])
def test_measurement_endpoint_refuses_impossible_values(vital, value):
    from pydantic import ValidationError

    from app.schemas import SessionMeasurementUpdate

    with pytest.raises(ValidationError):
        SessionMeasurementUpdate(vital=vital, value=value)


def test_spoken_rejection_stays_in_engine_state_only():
    """A refused spoken value is nurse-visible but is NOT session metadata,
    so it can never reach the Stage-1 HIS payload."""
    state = ScreeningState(session_id="s1")
    accepted, rejected = check_vitals({"temperature": 50})
    state.vitals.update(accepted)
    record_rejections(state, rejected, source="reported")

    # What the HIS would publish is built from session metadata vitals, which
    # this path never writes to — the rejection lives on the engine state.
    assert state.rejected_vitals["temp"]["value"] == 50
    assert "temp" not in state.vitals
    assert "temp" not in effective_vitals(state)
