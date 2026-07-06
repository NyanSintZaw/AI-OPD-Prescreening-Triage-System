"""Deterministic complaint-category → department resolution.

Encodes the MFU routing manual: levels 1–2 always go to the emergency
department; children under 15 go to pediatrics unless an emergency or an
obstetric case; specialty clinics accept directly only when their acceptance
criteria hold, otherwise the patient starts at general OPD (the manual's ENT
pattern). Only ``opd_*`` codes (or ``emergency``) are ever returned.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .criteria_models import ScreeningCriteria
from .evaluator import age_in_band, evaluate_condition

PEDIATRIC_DEPARTMENT = "opd_pediatrics"
DEFAULT_DEPARTMENT = "opd_general"


@dataclass(frozen=True)
class DepartmentDecision:
    department_code: str
    reason_en: str
    reason_th: str
    citation: str = ""


def resolve_department(
    *,
    level: int,
    complaint_category: str | None,
    findings: Mapping[str, str],
    vitals: Mapping[str, float],
    age_years: float | None,
    criteria: ScreeningCriteria,
    emergency_department_code: str | None = None,
) -> DepartmentDecision:
    if level <= 2:
        return DepartmentDecision(
            department_code=emergency_department_code or "emergency",
            reason_en="Urgent condition — emergency department",
            reason_th="ภาวะเร่งด่วน ส่งห้องฉุกเฉิน",
            citation="MFU Triage — ประเภทฉุกเฉินส่งห้องอุบัติเหตุและฉุกเฉินทันที",
        )

    # Children under 15 see pediatrics for non-obstetric OPD complaints.
    child_band = criteria.age_bands.get("child_any")
    is_child = (
        age_years is not None
        and child_band is not None
        and age_in_band(age_years, child_band)
    )
    if is_child and complaint_category not in ("pregnancy", "gynecology"):
        return DepartmentDecision(
            department_code=PEDIATRIC_DEPARTMENT,
            reason_en="Patient under 15 years — pediatrics",
            reason_th="ผู้ป่วยอายุน้อยกว่า 15 ปี ส่งหน่วยเด็กป่วย",
            citation="MFU routing — ผู้ป่วยกรณีอื่น อายุน้อยกว่า 15 ปี → เด็กป่วย",
        )

    kwargs = dict(
        findings=findings,
        vitals=vitals,
        age_years=age_years,
        age_bands=criteria.age_bands,
    )
    entries = [
        e for e in criteria.routing_table
        if e.complaint_category == (complaint_category or "generic")
    ]
    for entry in entries:
        if not entry.specialty_conditions:
            return DepartmentDecision(
                department_code=entry.department_code,
                reason_en=f"Routing rule for {entry.complaint_category}",
                reason_th=f"เกณฑ์การส่งต่อสำหรับอาการกลุ่ม {entry.complaint_category}",
                citation=entry.citation,
            )
        if any(evaluate_condition(cond, **kwargs) for cond in entry.specialty_conditions):
            return DepartmentDecision(
                department_code=entry.department_code,
                reason_en=f"Meets {entry.department_code} acceptance criteria",
                reason_th=f"เข้าเกณฑ์รับตรวจของ {entry.department_code}",
                citation=entry.citation,
            )
    if entries:
        # Specialty criteria not met — start at the fallback clinic first.
        entry = entries[0]
        return DepartmentDecision(
            department_code=entry.fallback_department_code,
            reason_en=(
                f"Does not meet {entry.department_code} acceptance criteria — "
                "screened at general OPD first"
            ),
            reason_th=(
                f"ไม่เข้าเกณฑ์รับตรวจตรงของ {entry.department_code} "
                "ให้ตรวจที่ OPD ทั่วไปก่อน"
            ),
            citation=entry.citation,
        )

    return DepartmentDecision(
        department_code=DEFAULT_DEPARTMENT,
        reason_en="No specific routing rule — general OPD",
        reason_th="ไม่มีเกณฑ์เฉพาะ ส่ง OPD ทั่วไป",
    )
