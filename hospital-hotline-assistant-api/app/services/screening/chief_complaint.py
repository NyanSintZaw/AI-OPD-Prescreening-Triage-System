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


def _complaint_text(state, criteria) -> str | None:
    if state.chief_complaint and str(state.chief_complaint).strip():
        return str(state.chief_complaint).strip()
    # Fallback: humanize category when intake never captured free text.
    # Labels come from the criteria document's own templates (single source
    # of truth — no second hardcoded map); unknown category → raw id.
    category = getattr(state, "complaint_category", None)
    if not category or category == "generic":
        return None
    lang = "th" if getattr(state, "language", "th") == "th" else "en"
    for template in getattr(criteria, "complaint_templates", None) or []:
        if template.category == category:
            return template.label_th if lang == "th" else template.label_en
    return str(category)


def format_chief_complaint_summary(state, criteria=None) -> str:
    """Compose a nurse-readable sentence from chief complaint + OLDCARTS slots.

    Examples (en):
      - "Fever for one day prior to hospital visit."
      - "Chest pain in the left chest for 2 hours prior to hospital visit."
      - "Sore throat."
    Thai mirrors the same structure with natural word order.
    """
    language = "th" if getattr(state, "language", "th") == "th" else "en"
    slots = getattr(state, "slots", None) or {}
    complaint = _complaint_text(state, criteria)
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
