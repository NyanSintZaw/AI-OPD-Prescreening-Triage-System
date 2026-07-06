"""Deterministic red-flag evaluation over structured findings.

Runs every turn (NHS Pathways clinical-hierarchy pattern): level-1
organ-failure criteria first, then danger vitals, fast tracks, department
red-flag rules, and triage tuples. Operates only on canonical finding ids and
numeric vitals — never on raw conversation text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .criteria_models import ScreeningCriteria
from .evaluator import evaluate_condition


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    source: str  # "level1" | "danger_vitals" | "fast_track" | "department_rule" | "triage_tuple"
    level: int
    label_en: str
    label_th: str
    citation: str
    department_code: str | None = None


def evaluate_red_flags(
    *,
    findings: Mapping[str, str],
    vitals: Mapping[str, float],
    age_years: float | None,
    criteria: ScreeningCriteria,
) -> list[RuleHit]:
    """Return every fired rule, ordered most severe first."""

    kwargs = dict(
        findings=findings,
        vitals=vitals,
        age_years=age_years,
        age_bands=criteria.age_bands,
    )
    hits: list[RuleHit] = []

    for rule in criteria.level1_criteria:
        if evaluate_condition(rule.condition, **kwargs):
            hits.append(RuleHit(
                rule_id=rule.id, source="level1", level=1,
                label_en=rule.label_en, label_th=rule.label_th,
                citation=rule.citation, department_code="emergency",
            ))

    for dv in criteria.danger_vitals:
        if evaluate_condition(dv.condition, **kwargs):
            hits.append(RuleHit(
                rule_id=dv.id, source="danger_vitals", level=dv.level,
                label_en=dv.label_en, label_th=dv.label_th,
                citation=dv.citation, department_code="emergency",
            ))

    for ft in criteria.fast_tracks:
        if evaluate_condition(ft.condition, **kwargs):
            hits.append(RuleHit(
                rule_id=ft.id, source="fast_track", level=ft.level,
                label_en=ft.label_en, label_th=ft.label_th,
                citation=ft.citation, department_code=ft.department_code,
            ))

    for dr in criteria.department_rules:
        if evaluate_condition(dr.condition, **kwargs):
            hits.append(RuleHit(
                rule_id=dr.id, source="department_rule", level=dr.min_level,
                label_en=dr.label_en, label_th=dr.label_th,
                citation=dr.citation, department_code=dr.department_code,
            ))

    for tup in criteria.triage_tuples:
        if all(findings.get(fid) == "present" for fid in tup.findings_all) and (
            not tup.risk_factors_any
            or any(findings.get(fid) == "present" for fid in tup.risk_factors_any)
        ):
            hits.append(RuleHit(
                rule_id=tup.id, source="triage_tuple", level=tup.force_min_level,
                label_en=tup.label_en, label_th=tup.label_th,
                citation=tup.citation, department_code="emergency",
            ))

    hits.sort(key=lambda h: h.level)
    return hits
