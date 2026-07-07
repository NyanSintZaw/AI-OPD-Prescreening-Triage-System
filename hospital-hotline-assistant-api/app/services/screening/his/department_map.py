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


def his_department_name(code: str | None) -> str | None:
    """Hospital department string for one of our codes; None if unmapped."""
    if code is None:
        return None
    return CODE_TO_HIS.get(code)
