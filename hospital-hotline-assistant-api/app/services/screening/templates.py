"""Deterministic bilingual reply templates.

Safety-critical wording lives here (and in the criteria question templates),
not in the model. Every engine reply has a template fallback so a validator
failure can always degrade to nurse-approved text.
"""

from __future__ import annotations

CONTACT_QUESTION = {
    "en": "Would you like the hospital to contact you afterwards? (yes/no)",
    "th": "หลังจากนี้ต้องการให้โรงพยาบาลติดต่อกลับไหมคะ (ต้องการ/ไม่ต้องการ)",
}

CONTACT_ASK_PHONE = {
    "en": "Certainly. What phone number should we call?",
    "th": "ได้ค่ะ ขอทราบเบอร์โทรศัพท์ที่สะดวกให้ติดต่อกลับได้ไหมคะ",
}

CONTACT_CLARIFY = {
    "en": "Just to confirm — would you like the hospital to contact you? (yes/no)",
    "th": "ขอยืนยันอีกครั้งนะคะ ต้องการให้โรงพยาบาลติดต่อกลับไหมคะ (ต้องการ/ไม่ต้องการ)",
}

CONTACT_CONFIRM_YES = {
    "en": "Thank you. The hospital will contact you. Your screening result and patient ID will be shown now. Take care.",
    "th": "ขอบคุณค่ะ ทางโรงพยาบาลจะติดต่อกลับนะคะ ระบบจะแสดงผลการคัดกรองและรหัสผู้ป่วยให้ตอนนี้ค่ะ ดูแลสุขภาพนะคะ",
}

CONTACT_CONFIRM_NO = {
    "en": "Understood — we won't contact you. Your screening result and patient ID will be shown now. Take care.",
    "th": "รับทราบค่ะ จะไม่มีการติดต่อกลับนะคะ ระบบจะแสดงผลการคัดกรองและรหัสผู้ป่วยให้ตอนนี้ค่ะ ดูแลสุขภาพนะคะ",
}

ESCALATION = {
    "en": "I'd like a nurse to help you directly. Please wait a moment — our staff have been notified and will assist you shortly.",
    "th": "ขอให้พยาบาลดูแลคุณโดยตรงนะคะ กรุณารอสักครู่ เจ้าหน้าที่ได้รับแจ้งแล้วและจะมาช่วยเหลือคุณเร็ว ๆ นี้ค่ะ",
}

EMERGENCY_EXPLAIN = {
    "en": (
        "Based on what you've told me, you should be seen right away. "
        "Please go to the Emergency Department now — staff there have been notified. "
    ),
    "th": (
        "จากอาการที่เล่ามา ควรได้รับการตรวจโดยเร็วที่สุดค่ะ "
        "กรุณาไปที่ห้องฉุกเฉินตอนนี้เลยนะคะ เจ้าหน้าที่ได้รับแจ้งแล้วค่ะ "
    ),
}

OPD_EXPLAIN = {
    "en": (
        "Thank you for the details. Based on your symptoms, the right place for you is {department}. "
        "Our staff will take care of you there. "
    ),
    "th": (
        "ขอบคุณสำหรับข้อมูลค่ะ จากอาการของคุณ แผนกที่เหมาะสมคือ{department} "
        "เจ้าหน้าที่จะดูแลคุณต่อที่นั่นนะคะ "
    ),
}

REPEAT_GUIDANCE = {
    "en": "Your screening is complete. Please proceed to {department} — staff there will take care of you. If your symptoms change or worsen, please tell our staff immediately.",
    "th": "การคัดกรองเสร็จสิ้นแล้วค่ะ กรุณาไปที่{department} เจ้าหน้าที่จะดูแลคุณต่อนะคะ หากอาการเปลี่ยนแปลงหรือแย่ลง กรุณาแจ้งเจ้าหน้าที่ทันทีค่ะ",
}

VOICE_GREETING = {
    "en": "Hello, this is the hospital screening assistant. What symptoms are you experiencing today?",
    "th": "สวัสดีค่ะ ระบบผู้ช่วยคัดกรองของโรงพยาบาลค่ะ วันนี้มีอาการอะไรให้ช่วยดูแลคะ",
}

# Fallback department display names; the engine overrides these with the
# database's bilingual names when available.
DEPARTMENT_NAMES: dict[str, dict[str, str]] = {
    "emergency": {"en": "the Emergency Department", "th": "ห้องฉุกเฉิน"},
    "opd_general": {"en": "OPD General Practice", "th": "OPD เวชปฏิบัติทั่วไป"},
    "opd_internal_medicine": {"en": "OPD Internal Medicine", "th": "OPD อายุรกรรม"},
    "opd_pediatrics": {"en": "OPD Pediatrics", "th": "OPD กุมารเวชกรรม"},
    "opd_cardiology": {"en": "OPD Cardiology", "th": "OPD โรคหัวใจ"},
    "opd_orthopedics": {"en": "OPD Orthopedics", "th": "OPD กระดูกและข้อ"},
    "opd_ent": {"en": "OPD ENT", "th": "OPD หู คอ จมูก"},
    "opd_surgery": {"en": "OPD Surgery", "th": "OPD ศัลยกรรม"},
    "opd_ophthalmology": {"en": "OPD Ophthalmology", "th": "OPD จักษุ"},
    "opd_psychiatry": {"en": "OPD Psychiatry", "th": "OPD จิตเวช"},
    "opd_obgyn": {"en": "OPD Obstetrics & Gynecology", "th": "OPD สูตินรีเวช"},
}


def department_display(code: str, language: str) -> str:
    entry = DEPARTMENT_NAMES.get(code)
    if entry is None:
        return code
    return entry.get(language) or entry["en"]
