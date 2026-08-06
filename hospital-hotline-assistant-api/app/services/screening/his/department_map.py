"""Map our internal department codes to the hospital's exact department
strings (as they appear in the HIS visit records).

Used by both write-back stages so the hospital side sees names its own
staff recognize. The verbatim strings come from the MFU 7-day prescreen
export. Departments the triage engine does not route to (dialysis, PCU,
after-hours SMC, physiotherapy, service points) are intentionally absent —
they are valid HIS destinations but not triage outcomes.
"""

from __future__ import annotations

# our code -> hospital department string (verbatim from the HIS export)
CODE_TO_HIS: dict[str, str] = {
    "emergency": "แผนก ER (อุบัติเหตุและฉุกเฉิน)",
    "opd_general": "แผนก OPD GP (ทั่วไป ชั้น1)",
    "opd_internal_medicine": "แผนก OPD MED (อายุรกรรม)",
    "opd_pediatrics": "แผนก OPD PEDIATRIC (กุมารเวชกรรม)",
    "opd_cardiology": "แผนก OPD HEART (หน่วยตรวจหัวใจและหลอดเลือด)",
    "opd_orthopedics": "แผนก OPD ORTHOPEDIC (โรคกระดูกและข้อ)",
    "opd_ent": "แผนก OPD E.N.T (หู คอ จมูก)",
    "opd_surgery": "แผนก OPD SURGICAL (ศัลยศาสตร์)",
    "opd_ophthalmology": "แผนก OPD EYE (ตา)",
    "opd_psychiatry": "แผนก จิตเวช",
    "opd_obgyn": "แผนก OPD OB-GYN (สูติ-นรีเวชกรรม)",
}


# ⚠️ PLACEHOLDER MASTER DATA — INVENTED BY US, NOT CONFIRMED BY THE HOSPITAL.
# Destination service point + department ids for POST /patient-assignments,
# shaped like the contract's SP_ER_01 / DEPT_ER samples. Must stay in lockstep
# with SERVICE_POINTS in hospital-his-mock/his_mock/database.py. Replace every
# value with iMed's real codes before any UAT call.
# Source table: docs/imed-integration-plan.md §Department master data.
CODE_TO_SPID: dict[str, str] = {
    "emergency": "SP_ER_01",
    "opd_general": "SP_OPD_GP_01",
    "opd_internal_medicine": "SP_OPD_MED_01",
    "opd_pediatrics": "SP_OPD_PED_01",
    "opd_cardiology": "SP_OPD_HEART_01",
    "opd_orthopedics": "SP_OPD_ORTHO_01",
    "opd_ent": "SP_OPD_ENT_01",
    "opd_surgery": "SP_OPD_SURG_01",
    "opd_ophthalmology": "SP_OPD_EYE_01",
    "opd_psychiatry": "SP_OPD_PSY_01",
    "opd_obgyn": "SP_OPD_OBGYN_01",
}


def his_service_point(code: str | None) -> str | None:
    """Destination ``assign_spid`` for one of our codes; None if unmapped.

    None must never be sent as a made-up id — the caller records the
    assignment as skipped instead."""
    if code is None:
        return None
    return CODE_TO_SPID.get(code)


def his_department_name(code: str | None) -> str | None:
    """Hospital department string for one of our codes; None if unmapped."""
    if code is None:
        return None
    return CODE_TO_HIS.get(code)
