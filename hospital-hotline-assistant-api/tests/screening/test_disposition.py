"""Disposition tests: MOPH level + department, most severe rule wins."""

import pytest

from app.services.screening.rules.disposition import decide


def dispose(criteria, findings=None, vitals=None, age=None, category=None):
    return decide(
        findings=findings or {},
        vitals=vitals or {},
        age_years=age,
        complaint_category=category,
        criteria=criteria,
    )


def test_level1_cardiac_arrest_goes_to_emergency(criteria):
    result = dispose(criteria, {"cardiac_arrest": "present"}, age=50)
    assert result.level == 1
    assert result.department_code == "emergency"
    assert result.color == "Red"
    assert any(r.rule_id == "l1_cardiac_arrest" for r in result.reasons)


def test_level2_tuple_chest_pain_sweating(criteria):
    result = dispose(
        criteria, {"chest_pain": "present", "diaphoresis": "present"}, age=50,
        category="chest_pain",
    )
    assert result.level == 2
    assert result.department_code == "emergency"


def test_level1_beats_level2(criteria):
    result = dispose(
        criteria,
        {"cardiac_arrest": "present", "chest_pain": "present", "diaphoresis": "present"},
        age=50,
    )
    assert result.level == 1


def test_severe_pain_without_red_flags_is_urgent(criteria):
    result = dispose(
        criteria, {"back_pain_radiating_leg": "present"}, {"pain_score": 7}, age=40,
        category="musculoskeletal",
    )
    assert result.level == 3
    assert result.department_code == "opd_orthopedics"
    assert any(r.rule_id == "scale_severe_no_red_flags" for r in result.reasons)


def test_severe_pain_with_high_risk_context_escalates(criteria):
    # chest pain + pain 8: the surgery critical-site rule (L2) fires first
    result = dispose(criteria, {"chest_pain": "present"}, {"pain_score": 8}, age=40)
    assert result.level == 2
    assert result.department_code == "emergency"


def test_resource_band_two_systemic_findings_urgent(criteria):
    result = dispose(
        criteria, {"cough": "present", "fever": "present", "vomiting": "present"},
        age=30, category="fever",
    )
    assert result.level == 3
    assert result.department_code == "opd_general"


def test_single_minor_finding_less_urgent(criteria):
    result = dispose(criteria, {"cough": "present"}, age=30, category="dyspnea_cough")
    assert result.level == 4
    assert result.department_code == "opd_general"


def test_no_findings_non_urgent(criteria):
    result = dispose(criteria, age=30, category="generic")
    assert result.level == 5
    assert result.department_code == "opd_general"


def test_heart_failure_signs_route_cardiology(criteria):
    result = dispose(
        criteria, {"cough": "present", "orthopnea": "present"},
        age=65, category="dyspnea_cough",
    )
    assert result.level == 4
    assert result.department_code == "opd_cardiology"


def test_reasons_include_department_citation(criteria):
    result = dispose(criteria, {"tinnitus": "present"}, age=40, category="ear")
    dept_reasons = [r for r in result.reasons if r.rule_id == "department_routing"]
    assert len(dept_reasons) == 1
    assert dept_reasons[0].text_th  # bilingual reasoning present
    assert dept_reasons[0].text_en


def test_age_assumed_flagged_when_unknown(criteria):
    assert dispose(criteria, {"cough": "present"}).age_assumed is True
    assert dispose(criteria, {"cough": "present"}, age=30).age_assumed is False


def test_thai_labels_present_on_all_hits(criteria):
    result = dispose(
        criteria, {"chest_pain": "present", "diaphoresis": "present"}, age=50,
    )
    for hit in result.rule_hits:
        assert hit.label_th.strip()
        assert hit.label_en.strip()
