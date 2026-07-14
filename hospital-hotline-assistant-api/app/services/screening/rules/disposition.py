"""Deterministic MOPH ED Triage disposition.

Order of authority (ESI v5 A/B/C/D style):
level-1 hits → level-2 hits (danger vitals, fast tracks, department rules,
triage tuples) → pain/distress scale escalation → resource-style banding for
levels 3–5. The level is internal — patients only ever see the department.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .criteria_models import ScreeningCriteria
from .department_map import DepartmentDecision, resolve_department
from .red_flags import RuleHit, evaluate_red_flags

LEVEL_META = {
    1: {"color": "Red", "label": "Immediate", "response_time": "Immediate"},
    2: {"color": "Orange", "label": "Emergent", "response_time": "10-15 minutes"},
    3: {"color": "Yellow", "label": "Urgent", "response_time": "60 minutes"},
    4: {"color": "Green", "label": "Less Urgent", "response_time": "120 minutes"},
    5: {"color": "White", "label": "Non-Urgent", "response_time": "240 minutes"},
}

# Findings that make severe pain (>=8) an emergency rather than urgent —
# ports the legacy evaluate_scale_override high-risk context.
HIGH_RISK_PAIN_FINDINGS = frozenset({
    "chest_pain", "headache", "abdominal_pain", "pregnancy", "major_trauma_mechanism",
    "dyspnea", "severe_bleeding", "active_bleeding", "confusion", "syncope_24h",
    "limb_weakness", "slurred_speech", "facial_droop",
})

# Present findings that indicate a systemic/multi-resource case for banding.
SYSTEMIC_FINDINGS = frozenset({
    "fever", "high_fever", "vomiting", "diarrhea", "dyspnea", "confusion",
    "syncope_24h", "vaginal_bleeding", "hemoptysis", "epistaxis", "edema",
})


@dataclass(frozen=True)
class DispositionReason:
    rule_id: str
    text_en: str
    text_th: str
    citation: str = ""


@dataclass(frozen=True)
class DispositionResult:
    level: int
    department_code: str
    color: str
    label: str
    response_time: str
    reasons: list[DispositionReason] = field(default_factory=list)
    rule_hits: list[RuleHit] = field(default_factory=list)
    age_assumed: bool = False


def _scale_escalation(
    findings: Mapping[str, str],
    vitals: Mapping[str, float],
) -> tuple[int | None, DispositionReason | None]:
    """Pain/distress scale overrides (legacy evaluate_scale_override parity)."""

    pain = vitals.get("pain_score")
    distress = vitals.get("distress_score")
    present = {fid for fid, state in findings.items() if state == "present"}

    if pain is not None and pain >= 8 and present & HIGH_RISK_PAIN_FINDINGS:
        return 2, DispositionReason(
            rule_id="scale_pain_high_risk",
            text_en="Severe pain score with high-risk context",
            text_th="คะแนนปวดรุนแรงร่วมกับบริบทความเสี่ยงสูง",
            citation="MFU Triage — Pain score ≥ 7 อวัยวะสำคัญ / scale override",
        )
    if distress is not None and distress >= 8 and "dyspnea" in present:
        return 2, DispositionReason(
            rule_id="scale_distress_respiratory",
            text_en="Severe breathing distress score with respiratory symptoms",
            text_th="คะแนนหายใจลำบากรุนแรงร่วมกับอาการทางเดินหายใจ",
            citation="MFU Triage — scale override",
        )
    if (pain is not None and pain >= 7) or (distress is not None and distress >= 7):
        return 3, DispositionReason(
            rule_id="scale_severe_no_red_flags",
            text_en="Severe pain/distress score without emergency red flags",
            text_th="คะแนนปวด/หายใจลำบากรุนแรงโดยไม่มีสัญญาณอันตราย",
            citation="MFU Triage — scale override",
        )
    return None, None


def _resource_band(findings: Mapping[str, str]) -> int:
    """Levels 3–5 by an ESI-style resource estimate over present findings."""

    present = {fid for fid, state in findings.items() if state == "present"}
    systemic = present & SYSTEMIC_FINDINGS
    if len(systemic) >= 2 or len(present) >= 4:
        return 3
    if present:
        return 4
    return 5


def decide(
    *,
    findings: Mapping[str, str],
    vitals: Mapping[str, float],
    age_years: float | None,
    complaint_category: str | None,
    criteria: ScreeningCriteria,
) -> DispositionResult:
    hits = evaluate_red_flags(
        findings=findings, vitals=vitals, age_years=age_years, criteria=criteria,
    )
    reasons = [
        DispositionReason(
            rule_id=h.rule_id, text_en=h.label_en, text_th=h.label_th, citation=h.citation,
        )
        for h in hits
    ]

    if hits and hits[0].level <= 2:
        level = hits[0].level
    else:
        scale_level, scale_reason = _scale_escalation(findings, vitals)
        if scale_level is not None and scale_reason is not None:
            level = scale_level
            reasons.append(scale_reason)
        else:
            level = _resource_band(findings)
            reasons.append(DispositionReason(
                rule_id=f"resource_band_level_{level}",
                text_en=f"No red flags; symptom profile fits level {level}",
                text_th=f"ไม่พบสัญญาณอันตราย ลักษณะอาการเข้ากับระดับ {level}",
            ))

    dept: DepartmentDecision = resolve_department(
        level=level,
        complaint_category=complaint_category,
        findings=findings,
        vitals=vitals,
        age_years=age_years,
        criteria=criteria,
    )
    reasons.append(DispositionReason(
        rule_id="department_routing",
        text_en=dept.reason_en,
        text_th=dept.reason_th,
        citation=dept.citation,
    ))

    meta = LEVEL_META[level]
    return DispositionResult(
        level=level,
        department_code=dept.department_code,
        color=meta["color"],
        label=meta["label"],
        response_time=meta["response_time"],
        reasons=reasons,
        rule_hits=hits,
        age_assumed=age_years is None,
    )
