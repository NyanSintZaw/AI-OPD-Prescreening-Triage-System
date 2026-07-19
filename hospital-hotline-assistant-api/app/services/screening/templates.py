"""Deterministic bilingual reply templates.

Safety-critical wording lives here (and in the criteria question templates),
not in the model. Every engine reply has a template fallback so a validator
failure can always degrade to nurse-approved text.
"""

from __future__ import annotations

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

# Personalized variant once the visit link gives us the patient's name; used
# as the persisted first chat message AND the spoken call greeting.
GREETING_NAMED = {
    "en": (
        "Hello {name}, welcome — I'm the hospital screening assistant. "
        "What symptoms bring you in today?"
    ),
    "th": (
        "สวัสดีค่ะ คุณ{name} ยินดีต้อนรับค่ะ "
        "ดิฉันเป็นผู้ช่วยคัดกรองของโรงพยาบาลค่ะ วันนี้มีอาการอะไรให้ช่วยดูแลคะ"
    ),
}


def greeting_line(name: str | None, language: str) -> str:
    """Greeting + intake ask; personalized when the HIS gave us a name."""
    clean = (name or "").strip()
    if clean:
        return GREETING_NAMED.get(language, GREETING_NAMED["en"]).format(name=clean)
    return VOICE_GREETING.get(language, VOICE_GREETING["en"])


FOLLOW_UP_OFFER = {
    "en": (
        "Before you go — is there anything you'd like to ask or tell the doctor? "
        "I'll note it for them."
    ),
    "th": (
        "ก่อนไปนะคะ มีอะไรอยากถามหรืออยากบอกคุณหมอไหมคะ "
        "ดิฉันจะจดไว้ให้ค่ะ"
    ),
}

FOLLOW_UP_PROMPT = {
    "en": "What would you like the doctor to know?",
    "th": "อยากบอกคุณหมอว่าอะไรคะ?",
}

FOLLOW_UP_ACK = {
    "en": "Got it — I've noted that for the doctor. Please proceed to {department}.",
    "th": "รับทราบค่ะ ดิฉันจดไว้ให้คุณหมอแล้ว กรุณาไปที่{department}นะคะ",
}

FOLLOW_UP_CLOSE = {
    "en": "Alright — please proceed to {department}. Take care.",
    "th": "ได้ค่ะ กรุณาไปที่{department}นะคะ ดูแลตัวเองด้วยนะคะ",
}

FOLLOW_UP_ACK_NAMED = {
    "en": "Got it, {name} — I've noted that for the doctor. Please proceed to {department}.",
    "th": "รับทราบค่ะ {name} ดิฉันจดไว้ให้คุณหมอแล้ว กรุณาไปที่{department}นะคะ",
}

FOLLOW_UP_CLOSE_NAMED = {
    "en": "Alright, {name} — please proceed to {department}. Take care.",
    "th": "ได้ค่ะ {name} กรุณาไปที่{department}นะคะ ดูแลตัวเองด้วยนะคะ",
}


def polite_name(name: str | None, language: str) -> str | None:
    """Address form of the HIS-recorded name for mid-conversation mentions:
    given name only, with the Thai honorific ('สมชาย ใจดี' -> 'คุณสมชาย',
    'Waraporn Srisuk' -> 'Waraporn'). None when no name is linked."""
    parts = (name or "").strip().split()
    if not parts:
        return None
    given = parts[0]
    return f"คุณ{given}" if language == "th" else given


def follow_up_ack(name: str | None, department: str, language: str) -> str:
    polite = polite_name(name, language)
    if polite:
        return FOLLOW_UP_ACK_NAMED[language].format(name=polite, department=department)
    return FOLLOW_UP_ACK[language].format(department=department)


def follow_up_close(name: str | None, department: str, language: str) -> str:
    polite = polite_name(name, language)
    if polite:
        return FOLLOW_UP_CLOSE_NAMED[language].format(name=polite, department=department)
    return FOLLOW_UP_CLOSE[language].format(department=department)

# Closing chip on per-finding red-flag choices; the extractor maps it to
# "all of the pending question's findings absent".
NONE_OF_THESE = {
    "en": "None of these",
    "th": "ไม่มีอาการเหล่านี้",
}

YES_NO_OPTIONS = {
    "en": [
        {"id": "yes", "label": "Yes"},
        {"id": "no", "label": "No"},
    ],
    "th": [
        {"id": "yes", "label": "ใช่"},
        {"id": "no", "label": "ไม่"},
    ],
}

VOICE_DIDNT_HEAR = {
    "en": "Sorry, I didn't catch that. Could you say it again?",
    "th": "ขอโทษค่ะ ไม่ได้ยินชัดเจน ช่วยพูดอีกครั้งได้ไหมคะ",
}

VOICE_ERROR = {
    "en": "Sorry, something went wrong on our side. Could you repeat that?",
    "th": "ขอโทษค่ะ ระบบขัดข้องชั่วคราว ช่วยพูดอีกครั้งได้ไหมคะ",
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
