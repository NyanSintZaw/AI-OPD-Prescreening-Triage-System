"""Guardrail-precedence proof tests (external safety review).

Pins the claimed order of authority in ``disposition.decide``:

    level-1 criteria  >  danger vitals / triage tuples (level-2 hits)
    >  scale escalation  >  resource band (levels 3-5 only)

plus measured-vitals authority (``effective_vitals``: cuff beats spoken),
the BP-crisis rest-then-confirm flow, and the level<=2 => emergency
department forcing. Each test is a demonstration, not an assertion of
intent: it must FAIL if the code's precedence ever changes.

Parametrized over the v1 seed and the v2 criteria document wherever the
rule exists in both; v2-only where the rule is new (infant fever danger
vital, palpitations+syncope tuple).
"""

import json
import pathlib

import pytest

from app.services.bp_rest import (
    CRISIS_DBP,
    CRISIS_SBP,
    is_hypertensive_crisis,
)
from app.services.screening.rules.criteria_models import parse_criteria
from app.services.screening.rules.criteria_store import load_seed_criteria
from app.services.screening.rules.department_map import resolve_department
from app.services.screening.rules.disposition import (
    HIGH_RISK_PAIN_FINDINGS,
    _resource_band,
    _scale_escalation,
    decide,
)
from app.services.screening.rules.red_flags import evaluate_red_flags
from app.services.screening.state import ScreeningState
from app.services.screening.vitals import (
    check_vitals,
    effective_vitals,
    normalize_vitals,
)
from app.services.triage_service import _turn_context

DATA_DIR = pathlib.Path(__file__).resolve().parents[2] / "app" / "data"


def _load_json(version: str) -> dict:
    return json.loads(
        (DATA_DIR / f"screening_criteria_{version}.json").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="module")
def criteria_v2():
    return parse_criteria(_load_json("v2"))


@pytest.fixture(scope="module", params=["v1", "v2"])
def versioned_criteria(request, criteria_v2):
    # v1 via the same loader the engine's DB-empty fallback uses.
    return load_seed_criteria() if request.param == "v1" else criteria_v2


def dispose(criteria, findings=None, vitals=None, age=None, category=None):
    return decide(
        findings=findings or {},
        vitals=vitals or {},
        age_years=age,
        complaint_category=category,
        criteria=criteria,
    )


def hit_ids(result):
    return {h.rule_id for h in result.rule_hits}


def reason_ids(result):
    return {r.rule_id for r in result.reasons}


# Catalog findings referenced by NO rule condition in either version —
# they exist only to feed the resource band (verified below).
BENIGN_FINDINGS = ("cough", "sore_throat", "runny_nose", "nasal_congestion")


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_benign_findings_really_are_unruled(version):
    """Guard the premise of the band tests: no rule mentions these ids."""
    doc = _load_json(version)
    conditions = json.dumps([
        r.get("condition")
        for section in ("level1_criteria", "danger_vitals", "department_rules", "fast_tracks")
        for r in doc[section]
    ]) + json.dumps([
        t.get("findings_all", []) + t.get("risk_factors_any", [])
        for t in doc["triage_tuples"]
    ])
    catalog = doc["finding_catalog"]
    for fid in BENIGN_FINDINGS:
        assert fid in catalog, fid
        assert f'"{fid}"' not in conditions, f"{fid} is referenced by a rule; pick another"


# --- 1. Level-1 criteria beat everything -----------------------------------

@pytest.mark.parametrize("category", [None, "generic", "ear"])
def test_level1_fires_with_zero_supporting_evidence(versioned_criteria, category):
    """cardiac_arrest alone: band would say 4, pain says nothing, category is
    irrelevant — level is 1 and the department is emergency."""
    result = dispose(
        versioned_criteria,
        {"cardiac_arrest": "present"},
        {"pain_score": 0},
        age=40,
        category=category,
    )
    assert result.level == 1
    assert result.department_code == "emergency"
    assert "l1_cardiac_arrest" in hit_ids(result)
    # the band alone would NOT have produced level 1
    assert _resource_band({"cardiac_arrest": "present"}) == 4


def test_level1_beats_simultaneous_level2_hits(versioned_criteria):
    result = dispose(
        versioned_criteria,
        {"cardiac_arrest": "present", "chest_pain": "present", "diaphoresis": "present"},
        age=50,
    )
    assert result.level == 1
    assert result.rule_hits[0].source == "level1"


# --- 2. Danger vitals beat the resource band -------------------------------

def test_measured_bp_crisis_overrides_band4_profile(versioned_criteria):
    """One benign finding bands to 4; a 200/120 cuff reading disposes 2."""
    findings = {"cough": "present"}
    assert _resource_band(findings) == 4
    result = dispose(versioned_criteria, findings, {"sbp": 200, "dbp": 120}, age=40)
    assert result.level == 2
    assert result.department_code == "emergency"
    assert "dv_adult_bp_crisis" in hit_ids(result)


def test_low_spo2_with_dyspnea_is_level1_over_band(versioned_criteria):
    findings = {"dyspnea": "present"}
    assert _resource_band(findings) == 4
    result = dispose(versioned_criteria, findings, {"spo2": 88}, age=30)
    assert result.level == 1
    assert "l1_adult_spo2_low" in hit_ids(result)


def test_no_vitals_no_findings_is_level5_not_emergency(versioned_criteria):
    result = dispose(versioned_criteria, age=30, category="generic")
    assert result.level == 5
    assert result.rule_hits == []


# --- 3. Triage tuples force their min level --------------------------------

def test_tt_anaphylaxis_forces_level2_over_band4(versioned_criteria):
    """rash + lip swelling + vomiting: only one systemic finding, three
    present findings — band says 4; the tuple forces 2."""
    findings = {
        "rash_itching": "present",
        "lip_swelling": "present",
        "vomiting": "present",
    }
    assert _resource_band(findings) == 4
    result = dispose(versioned_criteria, findings, age=30, category="skin_rash")
    assert result.level == 2
    assert result.department_code == "emergency"
    assert "tt_anaphylaxis" in hit_ids(result)


def test_tt_palpitations_syncope_v2_forces_level2(criteria_v2):
    findings = {"palpitations": "present", "syncope_24h": "present"}
    hits = evaluate_red_flags(
        findings=findings, vitals={}, age_years=45, criteria=criteria_v2,
    )
    tuple_hits = [h for h in hits if h.rule_id == "tt_palpitations_syncope"]
    assert tuple_hits and tuple_hits[0].level == 2
    result = dispose(criteria_v2, findings, age=45, category="palpitations")
    assert result.level == 2
    assert result.department_code == "emergency"
    assert "tt_palpitations_syncope" in hit_ids(result)


# --- 4. Resource band is capped at level 3 ---------------------------------

def test_resource_band_never_upgrades_past_level3(versioned_criteria):
    """Four present findings with no red flags: exactly 3, never 2."""
    findings = {fid: "present" for fid in BENIGN_FINDINGS}
    result = dispose(versioned_criteria, findings, age=30, category="generic")
    assert result.level == 3
    assert result.rule_hits == []  # nothing fired — the band alone decided
    assert "resource_band_level_3" in reason_ids(result)
    # the helper itself can only return 3, 4 or 5
    assert _resource_band(findings) == 3
    assert _resource_band({}) == 5


# --- 5. Scale escalation ----------------------------------------------------

def test_pain8_with_high_risk_finding_escalates_to_2(versioned_criteria):
    """dyspnea is a HIGH_RISK_PAIN_FINDINGS member that fires no criteria
    rule by itself, so the level-2 outcome is attributable to the scale."""
    assert "dyspnea" in HIGH_RISK_PAIN_FINDINGS
    result = dispose(
        versioned_criteria, {"dyspnea": "present"}, {"pain_score": 8}, age=40,
    )
    assert result.rule_hits == []  # no red-flag rule fired
    assert result.level == 2
    assert result.department_code == "emergency"
    assert "scale_pain_high_risk" in reason_ids(result)


def test_pain8_without_high_risk_finding_is_level3_not_2(versioned_criteria):
    """Pinned current behavior: adult pain 8 with only a benign finding does
    NOT reach level 2 — it falls through to the pain>=7 branch and lands at
    urgent (3), which also overrides the band's 4."""
    findings = {"cough": "present"}
    result = dispose(versioned_criteria, findings, {"pain_score": 8}, age=40)
    assert result.level == 3
    assert result.level != 2
    assert "scale_severe_no_red_flags" in reason_ids(result)
    assert _resource_band(findings) == 4  # scale beat the band, not vice versa


def test_scale_escalation_unit_branches():
    level, reason = _scale_escalation({"dyspnea": "present"}, {"pain_score": 8})
    assert (level, reason.rule_id) == (2, "scale_pain_high_risk")
    level, reason = _scale_escalation({"cough": "present"}, {"pain_score": 8})
    assert (level, reason.rule_id) == (3, "scale_severe_no_red_flags")
    level, reason = _scale_escalation({"dyspnea": "present"}, {"distress_score": 8})
    assert (level, reason.rule_id) == (2, "scale_distress_respiratory")
    assert _scale_escalation({}, {"pain_score": 6}) == (None, None)


def test_level2_hit_preempts_scale_escalation(versioned_criteria):
    """When a criteria rule fires at <=2 the scale never runs: chest pain +
    pain 8 is level 2 via surg_severe_pain_critical_site, not the scale."""
    result = dispose(
        versioned_criteria, {"chest_pain": "present"}, {"pain_score": 8}, age=40,
    )
    assert result.level == 2
    assert "surg_severe_pain_critical_site" in hit_ids(result)
    assert "scale_pain_high_risk" not in reason_ids(result)


# --- 6. Measured vitals beat spoken vitals ---------------------------------

def test_measured_temp_beats_spoken_temp_infant_fever_v2(criteria_v2):
    """Mirrors nodes/dispose.py: decide(vitals=effective_vitals(state)).
    Spoken 37.2 in state.vitals, thermometer 39.5 in measured_vitals,
    6-month-old -> dv_infant_fever_1_12m fires level 2."""
    state = ScreeningState(
        session_id="test",
        vitals={"temp": 37.2},           # LLM-extracted (spoken)
        measured_vitals={"temp": 39.5},  # booth thermometer
        age_years=0.5,
    )
    merged = effective_vitals(state)
    assert merged["temp"] == 39.5  # measured wins the merge
    result = decide(
        findings=state.finding_states(),
        vitals=merged,
        age_years=state.age_years,
        complaint_category=state.complaint_category,
        criteria=criteria_v2,
    )
    assert result.level == 2
    assert result.department_code == "emergency"
    assert "dv_infant_fever_1_12m" in hit_ids(result)


def test_spoken_temp_alone_does_not_fire_infant_fever_v2(criteria_v2):
    """Control: same state without the measured reading stays sub-threshold."""
    state = ScreeningState(session_id="test", vitals={"temp": 37.2}, age_years=0.5)
    result = decide(
        findings=state.finding_states(),
        vitals=effective_vitals(state),
        age_years=state.age_years,
        complaint_category=None,
        criteria=criteria_v2,
    )
    assert "dv_infant_fever_1_12m" not in hit_ids(result)
    assert result.level > 2


# --- 7. BP-crisis rest-then-confirm ----------------------------------------

@pytest.mark.parametrize("version", ["v1", "v2"])
def test_bp_rest_thresholds_match_criteria_json(version):
    """bp_rest.py duplicates dv_adult_bp_crisis's thresholds as constants.
    This test FAILS if the JSON and the constants ever drift apart."""
    doc = _load_json(version)
    rule = next(r for r in doc["danger_vitals"] if r["id"] == "dv_adult_bp_crisis")
    clauses = {
        (c["vital"], c["op"], c["value"]) for c in rule["condition"]["any_of"]
    }
    # same values AND same strict-> semantics as is_hypertensive_crisis
    assert clauses == {("sbp", "gt", CRISIS_SBP), ("dbp", "gt", CRISIS_DBP)}
    assert (CRISIS_SBP, CRISIS_DBP) == (180, 110)


def test_is_hypertensive_crisis_boundary_matches_gt_op():
    assert not is_hypertensive_crisis(CRISIS_SBP, None)      # 180 exactly: no
    assert is_hypertensive_crisis(CRISIS_SBP + 1, None)
    assert not is_hypertensive_crisis(None, CRISIS_DBP)      # 110 exactly: no
    assert is_hypertensive_crisis(None, CRISIS_DBP + 1)
    assert not is_hypertensive_crisis(None, None)


def test_first_crisis_reading_is_withheld_from_the_engine(versioned_criteria):
    """First crisis reading: main.py stores bp_recheck_pending and opens the
    15-min rest window; _turn_context then strips the BP numbers so decide()
    cannot dispose emergency on the provisional reading."""
    metadata = {
        "visit": {},
        "vitals": {
            "systolic": 200,
            "diastolic": 120,
            "temperature": 37.0,
            "bp_recheck_pending": True,
        },
    }
    ctx = _turn_context(metadata)
    assert ctx is not None
    for key in ("systolic", "diastolic", "sbp", "dbp", "map", "pressure"):
        assert key not in ctx["vitals"]
    assert ctx["vitals"]["temperature"] == 37.0  # non-BP vitals still flow

    engine_vitals = normalize_vitals(ctx["vitals"])  # engine._apply_turn_context
    result = dispose(versioned_criteria, {}, engine_vitals, age=55)
    assert "dv_adult_bp_crisis" not in hit_ids(result)
    assert result.level > 2  # no emergency dispose on the provisional reading


def test_confirmatory_reading_disposes_emergency(versioned_criteria):
    """Post-rest reading carries no bp_recheck_pending flag (has_prior_window
    is true, so main.py never re-sets it): the BP reaches the engine and the
    danger-vital rule disposes level 2 / emergency."""
    metadata = {
        "visit": {},
        "vitals": {"systolic": 200, "diastolic": 120, "temperature": 37.0},
    }
    ctx = _turn_context(metadata)
    assert ctx is not None
    engine_vitals = normalize_vitals(ctx["vitals"])
    assert engine_vitals["sbp"] == 200 and engine_vitals["dbp"] == 120
    result = dispose(versioned_criteria, {}, engine_vitals, age=55)
    assert result.level == 2
    assert result.department_code == "emergency"
    assert "dv_adult_bp_crisis" in hit_ids(result)


# --- 8. Level <= 2 forces the emergency department -------------------------

@pytest.mark.parametrize("level", [1, 2])
@pytest.mark.parametrize("category", ["ear", "eye", "musculoskeletal", "generic", None])
def test_resolve_department_forces_emergency_at_level_le2(
    versioned_criteria, level, category
):
    decision = resolve_department(
        level=level,
        complaint_category=category,
        findings={},
        vitals={},
        age_years=40,
        criteria=versioned_criteria,
    )
    assert decision.department_code == "emergency"


def test_level2_ent_complaint_goes_to_emergency_not_ent_clinic(versioned_criteria):
    """Control pair: the same 'ear' category routes to a clinic at level 4,
    so the emergency outcome below is attributable to the level, not the
    category."""
    routine = dispose(
        versioned_criteria, {"tinnitus": "present"}, age=40, category="ear",
    )
    assert routine.level == 4
    assert routine.department_code != "emergency"

    emergent = dispose(
        versioned_criteria,
        {"epistaxis_uncontrolled": "present"},
        age=40,
        category="ear",
    )
    assert emergent.level == 2
    assert emergent.department_code == "emergency"


# --- 8. Impossible readings never reach the rules ---------------------------
#
# "Impossible" and "dangerous" are different axes. A cuff that slipped can
# report 300/220; that is >180 and would otherwise both open a 15-minute rest
# window and dispose an emergency off a reading that never happened. A real
# 250/130 crisis must still fire. These tests pin both halves.

def test_impossible_cuff_reading_never_disposes_emergency(versioned_criteria):
    criteria = versioned_criteria
    accepted, rejected = check_vitals({"systolic": 300, "diastolic": 220})
    assert rejected, "300/220 must be refused as physiologically impossible"

    state = ScreeningState(session_id="test", age_years=40.0)
    state.vitals.update(accepted)
    state.measured_vitals.update(accepted)
    result = decide(
        findings=state.finding_states(),
        vitals=effective_vitals(state),
        age_years=state.age_years,
        complaint_category=None,
        criteria=criteria,
    )
    assert "dv_adult_bp_crisis" not in hit_ids(result)
    assert result.level > 2


def test_real_crisis_reading_still_disposes_emergency(versioned_criteria):
    """Control: a critical-but-possible reading must NOT be filtered out."""
    criteria = versioned_criteria
    accepted, rejected = check_vitals({"systolic": 250, "diastolic": 130})
    assert not rejected

    state = ScreeningState(session_id="test", age_years=40.0)
    state.vitals.update(accepted)
    state.measured_vitals.update(accepted)
    result = decide(
        findings=state.finding_states(),
        vitals=effective_vitals(state),
        age_years=state.age_years,
        complaint_category=None,
        criteria=criteria,
    )
    assert "dv_adult_bp_crisis" in hit_ids(result)
    assert result.level <= 2
    assert result.department_code == "emergency"


def test_impossible_reading_is_not_a_crisis_so_opens_no_rest_window():
    """The rest window is for genuine crisis readings only — an impossible one
    is re-measured immediately instead."""
    accepted, rejected = check_vitals({"systolic": 300, "diastolic": 220})
    assert rejected
    # Nothing survives the filter, so there is no reading to call a crisis on.
    assert "sbp" not in accepted and "dbp" not in accepted
    # …while the crisis check itself is untouched for real readings.
    assert is_hypertensive_crisis(250, 130)
