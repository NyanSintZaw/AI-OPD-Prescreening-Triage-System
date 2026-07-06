"""Department routing tests: OPD-first, pediatric override, specialty-fail
falls back to general OPD (the MFU ENT pattern)."""

import pytest

from app.services.screening.rules.department_map import resolve_department


def route(criteria, category, findings=None, vitals=None, age=None, level=4):
    return resolve_department(
        level=level,
        complaint_category=category,
        findings=findings or {},
        vitals=vitals or {},
        age_years=age,
        criteria=criteria,
    )


def test_level_1_and_2_always_emergency(criteria):
    for level in (1, 2):
        decision = route(criteria, "ear", {"tinnitus": "present"}, age=30, level=level)
        assert decision.department_code == "emergency"


def test_child_routes_to_pediatrics(criteria):
    decision = route(criteria, "fever", {"fever": "present"}, age=8)
    assert decision.department_code == "opd_pediatrics"


def test_pregnant_teen_routes_to_obgyn_not_pediatrics(criteria):
    decision = route(criteria, "pregnancy", {"pregnancy": "present"}, age=14)
    assert decision.department_code == "opd_obgyn"


def test_ent_acceptance_met_goes_direct(criteria):
    decision = route(criteria, "ear", {"tinnitus": "present"}, age=40)
    assert decision.department_code == "opd_ent"


def test_ent_acceptance_failed_goes_general_opd_first(criteria):
    decision = route(criteria, "ear", {"ear_pain": "present"}, {"pain_score": 4}, age=40)
    assert decision.department_code == "opd_general"
    assert "OPD" in decision.reason_en


def test_ear_pain_severe_meets_ent_criteria(criteria):
    decision = route(criteria, "ear", {"ear_pain": "present"}, {"pain_score": 8}, age=40)
    assert decision.department_code == "opd_ent"


def test_nose_throat_hoarseness_over_2w_direct_ent(criteria):
    decision = route(criteria, "nose_throat", {"hoarseness_over_2w": "present"}, age=50)
    assert decision.department_code == "opd_ent"


def test_plain_sore_throat_general_first(criteria):
    decision = route(criteria, "nose_throat", {"sore_throat": "present"}, age=30)
    assert decision.department_code == "opd_general"


def test_psych_under_60_depression(criteria):
    decision = route(criteria, "mental_health", {"depression_symptoms": "present"}, age=45)
    assert decision.department_code == "opd_psychiatry"


def test_psych_over_60_first_episode_internal_medicine(criteria):
    decision = route(criteria, "mental_health", {"depression_symptoms": "present"}, age=70)
    assert decision.department_code == "opd_internal_medicine"


def test_auditory_hallucinations_psychiatry_any_age(criteria):
    decision = route(criteria, "mental_health", {"auditory_hallucinations": "present"}, age=70)
    assert decision.department_code == "opd_psychiatry"


def test_breast_routes_surgery(criteria):
    decision = route(criteria, "breast", {"breast_lump": "present"}, age=45)
    assert decision.department_code == "opd_surgery"


def test_abdominal_mass_routes_surgery(criteria):
    decision = route(criteria, "abdominal_pain", {"abdominal_mass": "present"}, age=50)
    assert decision.department_code == "opd_surgery"


def test_plain_abdominal_pain_internal_medicine(criteria):
    decision = route(criteria, "abdominal_pain", {"abdominal_pain": "present"}, age=50)
    assert decision.department_code == "opd_internal_medicine"


def test_fracture_routes_orthopedics(criteria):
    decision = route(criteria, "injury", {"fracture_suspected": "present"}, age=30)
    assert decision.department_code == "opd_orthopedics"


def test_old_head_injury_routes_surgery(criteria):
    decision = route(criteria, "injury", {"head_injury_over_24h": "present"}, age=30)
    assert decision.department_code == "opd_surgery"


def test_unknown_category_general(criteria):
    decision = route(criteria, "something_unmapped", {}, age=30)
    assert decision.department_code == "opd_general"


def test_only_opd_or_emergency_codes(criteria):
    for entry in criteria.routing_table:
        for code in (entry.department_code, entry.fallback_department_code):
            assert code == "emergency" or code.startswith("opd_")
