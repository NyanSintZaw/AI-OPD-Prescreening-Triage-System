"""Natural-language chief-complaint summary for nurse/HIS surfaces.

Template-composed (no LLM) so it never leaks triage level/color/diagnosis.
Used as ``symptoms_summary`` on dispose — the single choke point for nurse
queue, HIS write-back, and disease surveillance.
"""

from __future__ import annotations

from typing import Any, Mapping


def _slot(slots: Mapping[str, Any], key: str) -> str | None:
    value = slots.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _complaint_text(state) -> str | None:
    if state.chief_complaint and str(state.chief_complaint).strip():
        return str(state.chief_complaint).strip()
    # Fallback: humanize category when intake never captured free text.
    category = getattr(state, "complaint_category", None)
    if not category or category == "generic":
        return None
    labels = {
        "en": {
            "chest_pain": "chest pain",
            "dyspnea_cough": "breathing difficulty or cough",
            "abdominal_pain": "abdominal pain",
            "headache": "headache",
            "fever": "fever",
            "ear": "ear symptoms",
            "nose_throat": "sore throat or nasal symptoms",
            "eye": "eye symptoms",
            "injury": "injury",
            "pregnancy": "pregnancy-related symptoms",
            "mental_health": "mental health concerns",
            "musculoskeletal": "muscle or joint pain",
            "urinary": "urinary symptoms",
        },
        "th": {
            "chest_pain": "อาการเจ็บหน้าอก",
            "dyspnea_cough": "อาการหายใจลำบากหรือไอ",
            "abdominal_pain": "อาการปวดท้อง",
            "headache": "อาการปวดศีรษะ",
            "fever": "อาการไข้",
            "ear": "อาการทางหู",
            "nose_throat": "อาการเจ็บคอหรือจมูก",
            "eye": "อาการทางตา",
            "injury": "อาการบาดเจ็บ",
            "pregnancy": "อาการที่เกี่ยวกับการตั้งครรภ์",
            "mental_health": "อาการด้านสุขภาพจิต",
            "musculoskeletal": "อาการปวดกล้ามเนื้อหรือข้อ",
            "urinary": "อาการทางเดินปัสสาวะ",
        },
    }
    lang = "th" if getattr(state, "language", "th") == "th" else "en"
    return labels[lang].get(str(category))


def format_chief_complaint_summary(state) -> str:
    """Compose a nurse-readable sentence from chief complaint + OLDCARTS slots.

    Examples (en):
      - "Fever for one day prior to hospital visit."
      - "Chest pain in the left chest for 2 hours prior to hospital visit."
      - "Sore throat."
    Thai mirrors the same structure with natural word order.
    """
    language = "th" if getattr(state, "language", "th") == "th" else "en"
    slots = getattr(state, "slots", None) or {}
    complaint = _complaint_text(state)
    duration = _slot(slots, "duration") or _slot(slots, "onset")
    location = _slot(slots, "location")
    character = _slot(slots, "character")

    if language == "th":
        return _format_th(complaint, duration, location, character)
    return _format_en(complaint, duration, location, character)


def _format_en(
    complaint: str | None,
    duration: str | None,
    location: str | None,
    character: str | None,
) -> str:
    if not complaint:
        if duration:
            return f"Symptoms for {duration} prior to hospital visit."
        return "No structured chief complaint collected."

    # Avoid doubling if the free-text already embeds duration phrasing.
    lower = complaint.lower()
    has_time = duration and (
        duration.lower() in lower
        or any(w in lower for w in ("day", "hour", "week", "month", "since", "ago"))
    )

    parts: list[str] = [complaint]
    if character and character.lower() not in lower:
        parts[0] = f"{complaint} ({character})"
    if location and location.lower() not in lower:
        parts.append(f"in the {location}")
    if duration and not has_time:
        parts.append(f"for {duration} prior to hospital visit")

    sentence = " ".join(parts)
    if not sentence.endswith("."):
        sentence += "."
    # Capitalize first letter only (preserve Thai / mid-sentence casing).
    return sentence[0].upper() + sentence[1:] if sentence else sentence


def _format_th(
    complaint: str | None,
    duration: str | None,
    location: str | None,
    character: str | None,
) -> str:
    if not complaint:
        if duration:
            return f"มีอาการมา {duration} ก่อนมาโรงพยาบาล"
        return "ยังไม่มีข้อมูลอาการสำคัญที่ชัดเจน"

    parts: list[str] = [complaint]
    if character and character not in complaint:
        parts.append(f"ลักษณะ {character}")
    if location and location not in complaint:
        parts.append(f"บริเวณ {location}")
    if duration and duration not in complaint:
        parts.append(f"มา {duration} ก่อนมาโรงพยาบาล")
    return " ".join(parts)
