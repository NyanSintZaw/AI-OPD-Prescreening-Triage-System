"""Validation of the bundled screening criteria seed document.

``app/data/screening_criteria.json`` is THE criteria: the engine's DB-empty
fallback, what a fresh database seeds as version 1 active, and what
``scripts/deploy_criteria.py`` publishes. Standards-cited throughout (MOPH ED
Triage leading, ESI v5 referenced; docs/criteria-standards.md), with a
top-level ``source_standards`` provenance block.

These checks run over the WHOLE document — every routing category, template,
and red-flag question — so a future edit cannot quietly ship an uncited or
rule-less red flag.
"""

import json

import pytest

from app.services.screening.rules.criteria_store import (
    SEED_CRITERIA_PATH,
    load_seed_criteria,
)

EXPECTED_CATEGORIES = {
    "abdominal_pain", "administrative", "breast", "chest_pain",
    "chronic_followup", "dyspnea_cough", "ear", "eye", "fever", "forensic",
    "generic", "gi", "gynecology", "headache", "injury", "limb_vascular",
    "mental_health", "musculoskeletal", "nose_throat", "palpitations",
    "pregnancy", "skin_rash", "urinary", "wound_skin",
}


@pytest.fixture(scope="module")
def criteria():
    return load_seed_criteria()


def test_parses_clean(criteria):
    assert criteria.schema_version == 2


def test_source_standards_present(criteria):
    names = [s.name for s in criteria.source_standards]
    # MOPH ED Triage is the governing standard and must lead; ESI is a
    # structure/content reference only and comes last.
    assert "MOPH ED Triage" in names[0]
    moph = criteria.source_standards[0]
    assert moph.url.startswith("https://www.dms.go.th/")
    assert any("MFU" in n for n in names)
    esi = next(s for s in criteria.source_standards if "Emergency Severity Index" in s.name)
    assert esi is criteria.source_standards[-1]
    assert "does not implement" in esi.edition
    assert esi.url.startswith("https://")


def test_expected_category_set(criteria):
    assert {t.category for t in criteria.complaint_templates} == EXPECTED_CATEGORIES


def test_every_routing_category_has_template_or_generic(criteria):
    categories = {t.category for t in criteria.complaint_templates}
    assert "generic" in categories
    for entry in criteria.routing_table:
        assert entry.complaint_category in categories, entry.complaint_category


def test_generic_red_flag_coverage(criteria):
    # Universal red-flag questions are asked before every template's own
    # questions, so generic-path coverage = universal red flags + the generic
    # template's red flags (>= 4 total). The self-harm screen deliberately
    # lives only in the mental_health template (2026-08-20): an unclassified
    # "unwell" walk-in must not be asked about ending their life as question
    # three; spontaneous mentions still reach the confirm-before-fire gate.
    universal_rf = [q for q in criteria.universal_questions if q.kind == "red_flag"]
    generic = next(t for t in criteria.complaint_templates if t.category == "generic")
    generic_rf = [q for q in generic.questions if q.kind == "red_flag"]
    assert len(universal_rf) >= 1
    assert len(generic_rf) >= 3
    assert len(universal_rf) + len(generic_rf) >= 4
    # the generic red flags lead with MOPH and reference the ESI handbook
    for q in generic_rf:
        assert q.citation.startswith("MOPH ED Triage (5-level)"), q.id
        assert "ESI v5 Handbook" in q.citation, q.id


def test_all_templates_fully_bilingual(criteria):
    for template in criteria.complaint_templates:
        assert template.label_en.strip() and template.label_th.strip()
        # The cap guards INTERVIEW length — how much the patient is asked.
        # Measurement questions are booth actions, not interview turns (BP is
        # a standard vital in every template; temp only fires once fever is
        # reported), so they don't count. Runtime length is bounded
        # separately by question_budget. Cap is 10: dyspnea_cough carries a
        # fifth red flag (dc_retraction) because the MOPH SpO2 90–94% danger
        # band is gated on retraction and nothing else asks it.
        asked = [q for q in template.questions if q.kind != "measurement"]
        assert 1 <= len(asked) <= 10, template.category
        for q in template.questions:
            assert q.text_en.strip(), q.id
            assert q.text_th.strip(), q.id
            for opt in q.options:
                assert opt.text_en.strip() and opt.text_th.strip(), q.id


def test_all_red_flag_questions_cited(criteria):
    for template in criteria.complaint_templates:
        for q in template.questions:
            if q.kind == "red_flag":
                assert q.citation, f"{template.category}:{q.id} missing citation"


def test_all_red_flag_findings_are_rule_backed(criteria):
    # Every finding a red-flag question can set must be referenced by at
    # least one rule (level1 / danger vital / dept rule / tuple / fast track),
    # otherwise answering "yes" would never change the disposition. A tuple's
    # risk_factors_any counts: hemoptysis backs dc_hemoptysis only through
    # tt_tb_suspect's risk factors.
    referenced: set[str] = set()

    def walk(cond):
        if cond.finding_id:
            referenced.add(cond.finding_id)
        for child in [*cond.all_of, *cond.any_of]:
            walk(child)

    for rule in [
        *criteria.level1_criteria, *criteria.danger_vitals,
        *criteria.department_rules, *criteria.fast_tracks,
    ]:
        walk(rule.condition)
    for tup in criteria.triage_tuples:
        referenced.update(tup.findings_all)
        referenced.update(tup.risk_factors_any)

    for template in criteria.complaint_templates:
        for q in template.questions:
            if q.kind != "red_flag":
                continue
            assert any(fid in referenced for fid in q.finding_ids), (
                f"{template.category}:{q.id} red flag has no rule backing"
            )


def test_authors_vital_bounds_explicitly(criteria):
    """The document carries its own plausibility table rather than leaning on
    the code defaults, so a head nurse can retune it through the criteria
    lifecycle."""
    raw = json.loads(SEED_CRITERIA_PATH.read_text(encoding="utf-8"))
    assert "vital_bounds" in raw, "criteria must author vital_bounds"
    assert "cross_checks" in raw

    for name, bound in criteria.vital_bounds.items():
        assert bound.min < bound.max, name
        assert bound.retry_text_en.strip(), f"{name} missing English retry wording"
        assert bound.retry_text_th.strip(), f"{name} missing Thai retry wording"

    # Every vital the booth or the interview can collect must be bounded.
    for name in ("sbp", "dbp", "hr", "temp", "weight", "height", "age_years"):
        assert name in criteria.vital_bounds, f"{name} has no bound"


def test_bp_bounds_admit_a_real_hypertensive_crisis(criteria):
    """The bounds must never quietly filter out the readings the danger-vital
    rules exist to catch (dv_adult_bp_crisis fires above 180/110)."""
    assert criteria.vital_bounds["sbp"].contains(250)
    assert criteria.vital_bounds["dbp"].contains(140)


def test_unknown_department_code_is_rejected_at_validation(criteria):
    """A typo'd department used to pass validation and surface only as a
    silently dropped recommendation at runtime; now it fails at approval."""
    import pytest
    from app.services.screening.rules.criteria_models import parse_criteria

    payload = criteria.model_dump(mode="json")
    payload["routing_table"][0]["department_code"] = "opd_typo"
    with pytest.raises(ValueError, match="unknown department 'opd_typo'"):
        parse_criteria(payload)

    payload = criteria.model_dump(mode="json")
    payload["routing_table"][0]["fallback_department_code"] = "opd_nope"
    with pytest.raises(ValueError, match="unknown department 'opd_nope'"):
        parse_criteria(payload)

    payload = criteria.model_dump(mode="json")
    payload["department_rules"][0]["department_code"] = "er"
    with pytest.raises(ValueError, match="unknown department 'er'"):
        parse_criteria(payload)


def test_anchor_findings_exist_and_are_validated(criteria):
    """A template's anchor finding(s) drive the mid-interview category switch
    and the second-complaint red-flag screen; a typo must fail the deploy."""
    from app.services.screening.rules.criteria_models import parse_criteria

    anchored = [t for t in criteria.complaint_templates if t.anchor_finding_ids]
    assert {t.category for t in anchored} >= {
        "chest_pain", "abdominal_pain", "fever", "headache", "dyspnea_cough",
    }
    for template in anchored:
        for fid in template.anchor_finding_ids:
            assert fid in criteria.finding_catalog, f"{template.category}: {fid}"

    payload = criteria.model_dump(mode="json")
    payload["complaint_templates"][1]["anchor_finding_ids"] = ["chest_pian"]
    with pytest.raises(ValueError, match="unknown finding 'chest_pian'"):
        parse_criteria(payload)
