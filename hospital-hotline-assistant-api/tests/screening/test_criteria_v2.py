"""Validation of the v2 screening criteria seed document.

v2 = v1 + standards-cited breadth additions (MOPH ED Triage leading, ESI v5
referenced; docs/criteria-standards.md):
templates for the six formerly-orphaned routing categories, four new
categories (gi, skin_rash, chronic_followup, administrative), extra generic
red-flag questions, and a top-level ``source_standards`` provenance block.
"""

import json
import pathlib

import pytest

from app.services.screening.rules.criteria_models import parse_criteria

V2_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "app" / "data" / "screening_criteria_v2.json"
)

FORMERLY_ORPHANED = {
    "wound_skin", "gynecology", "breast", "palpitations", "limb_vascular", "forensic",
}
NEW_CATEGORIES = {"gi", "skin_rash", "chronic_followup", "administrative"}


@pytest.fixture(scope="module")
def criteria():
    return parse_criteria(json.loads(V2_PATH.read_text(encoding="utf-8")))


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


def test_every_routing_category_has_template_or_generic(criteria):
    categories = {t.category for t in criteria.complaint_templates}
    assert "generic" in categories
    for entry in criteria.routing_table:
        assert entry.complaint_category in categories, entry.complaint_category


def test_formerly_orphaned_categories_have_templates(criteria):
    categories = {t.category for t in criteria.complaint_templates}
    assert FORMERLY_ORPHANED <= categories


def test_new_categories_have_template_and_routing(criteria):
    categories = {t.category for t in criteria.complaint_templates}
    routed = {e.complaint_category for e in criteria.routing_table}
    assert NEW_CATEGORIES <= categories
    assert NEW_CATEGORIES <= routed


def test_generic_red_flag_coverage(criteria):
    # Universal red-flag questions are asked before every template's own
    # questions, so generic-path coverage = universal red flags + the generic
    # template's red flags. v2 adds 4 to generic on top of the universal
    # breathing question (>= 5 total).
    universal_rf = [q for q in criteria.universal_questions if q.kind == "red_flag"]
    generic = next(t for t in criteria.complaint_templates if t.category == "generic")
    generic_rf = [q for q in generic.questions if q.kind == "red_flag"]
    assert len(universal_rf) >= 1
    assert len(generic_rf) >= 4
    assert len(universal_rf) + len(generic_rf) >= 5
    # the new generic red flags lead with MOPH and reference the ESI handbook
    for q in generic_rf:
        assert q.citation.startswith("MOPH ED Triage (5-level)"), q.id
        assert "ESI v5 Handbook" in q.citation, q.id


def test_new_templates_fully_bilingual(criteria):
    new = FORMERLY_ORPHANED | NEW_CATEGORIES
    for template in criteria.complaint_templates:
        if template.category not in new:
            continue
        assert template.label_en.strip() and template.label_th.strip()
        assert 1 <= len(template.questions) <= 8, template.category
        for q in template.questions:
            assert q.text_en.strip(), q.id
            assert q.text_th.strip(), q.id
            for opt in q.options:
                assert opt.text_en.strip() and opt.text_th.strip(), q.id


def test_new_red_flag_questions_cited(criteria):
    new = FORMERLY_ORPHANED | NEW_CATEGORIES
    for template in criteria.complaint_templates:
        if template.category not in new:
            continue
        for q in template.questions:
            if q.kind == "red_flag":
                assert q.citation, f"{template.category}:{q.id} missing citation"


def test_new_red_flag_findings_are_rule_backed(criteria):
    # Every finding a new red-flag question can set must be referenced by at
    # least one rule (level1 / danger vital / dept rule / tuple / fast track),
    # otherwise answering "yes" would never change the disposition.
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

    new = FORMERLY_ORPHANED | NEW_CATEGORIES
    for template in criteria.complaint_templates:
        if template.category not in new:
            continue
        for q in template.questions:
            if q.kind != "red_flag":
                continue
            assert any(fid in referenced for fid in q.finding_ids), (
                f"{template.category}:{q.id} red flag has no rule backing"
            )


def test_v2_authors_vital_bounds_explicitly(criteria):
    """v2 carries its own plausibility table rather than leaning on the code
    defaults, so a head nurse can retune it through the criteria lifecycle."""
    raw = json.loads(V2_PATH.read_text(encoding="utf-8"))
    assert "vital_bounds" in raw, "v2 must author vital_bounds"
    assert "cross_checks" in raw

    for name, bound in criteria.vital_bounds.items():
        assert bound.min < bound.max, name
        assert bound.retry_text_en.strip(), f"{name} missing English retry wording"
        assert bound.retry_text_th.strip(), f"{name} missing Thai retry wording"

    # Every vital the booth or the interview can collect must be bounded.
    for name in ("sbp", "dbp", "hr", "temp", "weight", "height", "age_years"):
        assert name in criteria.vital_bounds, f"{name} has no bound"


def test_v2_bp_bounds_admit_a_real_hypertensive_crisis(criteria):
    """The bounds must never quietly filter out the readings the danger-vital
    rules exist to catch (dv_adult_bp_crisis fires above 180/110)."""
    assert criteria.vital_bounds["sbp"].contains(250)
    assert criteria.vital_bounds["dbp"].contains(140)
