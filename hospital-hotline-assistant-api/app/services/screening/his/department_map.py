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
# Destination department ids for POST /patient-assignments (Data Requirements
# V1 §3.1 base_department_id), shaped like the contract's DEPT_MED sample. We
# route at department granularity only — the hospital assigns the service
# point / room itself. Must stay in lockstep with SERVICE_POINTS in
# hospital-his-mock/his_mock/database.py. Replace every value with the real
# department master data before any UAT call.
CODE_TO_DEPT_ID: dict[str, str] = {
    "emergency": "DEPT_ER",
    "opd_general": "DEPT_GP",
    "opd_internal_medicine": "DEPT_MED",
    "opd_pediatrics": "DEPT_PED",
    "opd_cardiology": "DEPT_HEART",
    "opd_orthopedics": "DEPT_ORTHO",
    "opd_ent": "DEPT_ENT",
    "opd_surgery": "DEPT_SURG",
    "opd_ophthalmology": "DEPT_EYE",
    "opd_psychiatry": "DEPT_PSY",
    "opd_obgyn": "DEPT_OBGYN",
}


def his_department_id(code: str | None) -> str | None:
    """Destination ``base_department_id`` for one of our codes; None if
    unmapped. None must never be sent as a made-up id — the caller records
    the assignment as skipped instead."""
    if code is None:
        return None
    return CODE_TO_DEPT_ID.get(code)


def his_department_name(code: str | None) -> str | None:
    """Hospital department string for one of our codes; None if unmapped."""
    if code is None:
        return None
    return CODE_TO_HIS.get(code)
