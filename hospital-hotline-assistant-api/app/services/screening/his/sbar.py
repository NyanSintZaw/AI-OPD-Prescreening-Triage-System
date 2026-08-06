"""SBAR clinical handover for the hospital's iMed assignment API.

SBAR (Situation, Background, Assessment, Recommendation) is the standard
handover format between clinicians. iMed's variant splits Assessment into
three and adds Documentation — seven fields, all optional. Sending it switches
their flow to ``assignSbarVisit`` and returns an ``sbar_id``.

Two rules that are easy to get wrong:

**Always Thai.** Hospital staff read Thai regardless of the language the
patient chose at the booth. Note that ``classification["key_reason"]`` is
language-selected when the engine builds it (``nodes/dispose.py`` picks
``text_en`` for an English session), so it must NOT be dropped into an
always-Thai handover — build from ``disposition_reasons[].text_th`` instead
and fall back to ``key_reason`` only when that list is empty.

**No patient redaction.** ``validator.py`` and ``triage_payloads.py`` strip
triage level / colour / diagnosis because those surfaces are patient-facing.
SBAR is the opposite case: it goes to a clinician, and the triage level is the
single most useful thing in it. Do not apply the patient redaction here.

Pure — dict in, dict out. No DB, no network, no LLM.
"""

from __future__ import annotations

from typing import Any


def disposition_reason_texts(
    classification: dict[str, Any], *, prefer_thai: bool = False
) -> list[str]:
    """Flatten the engine's disposition_reasons into plain strings.

    Handles both string lists and the structured
    ``{rule_id, citation, text_en, text_th}`` shape. ``prefer_thai`` picks the
    Thai wording for the clinician-facing SBAR; the default English-first
    behaviour is what the Stage-1 referral has always used.
    """
    reasons = classification.get("disposition_reasons") or []
    out: list[str] = []
    for item in reasons:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            if prefer_thai:
                primary = item.get("text_th") or item.get("text_en")
            else:
                primary = item.get("text_en") or item.get("text_th")
            text = str(primary or item.get("rule_id") or "").strip()
            citation = str(item.get("citation") or "").strip()
            if text and citation:
                text = f"{text} ({citation})"
        else:
            text = str(item).strip()
        if text:
            out.append(text)
    return out


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _vitals_line(vitals: dict[str, Any]) -> str | None:
    """Booth measurements as one Thai line, with provenance."""
    parts: list[str] = []
    sbp, dbp = vitals.get("systolic"), vitals.get("diastolic")
    if sbp and dbp:
        parts.append(f"ความดัน {sbp}/{dbp}")
    if vitals.get("pulse_bpm"):
        parts.append(f"ชีพจร {vitals['pulse_bpm']}")
    if vitals.get("temperature"):
        parts.append(f"อุณหภูมิ {vitals['temperature']}")
    if vitals.get("weight_kg"):
        parts.append(f"น้ำหนัก {vitals['weight_kg']} กก.")
    if vitals.get("height_cm"):
        parts.append(f"ส่วนสูง {vitals['height_cm']} ซม.")
    if not parts:
        return None
    line = " ".join(parts)
    # "measured by a cuff at the booth" and "the patient said so" are very
    # different things to a clinician.
    if vitals.get("source") == "device":
        line += " (วัดที่บูธ)"
    elif vitals.get("source") == "manual":
        line += " (ผู้ป่วยแจ้ง)"
    return line


def _history_line(history: dict[str, Any]) -> str | None:
    labels = (
        ("chronic_conditions", "โรคประจำตัว"),
        ("allergies", "แพ้ยา/แพ้สาร"),
        ("past_surgeries", "เคยผ่าตัด"),
        ("family_history", "ประวัติครอบครัว"),
        ("smoking_alcohol", "สูบบุหรี่/ดื่มสุรา"),
    )
    parts = [f"{label}: {v}" for key, label in labels if (v := _clean(history.get(key)))]
    if history.get("is_first_time"):
        parts.append("ผู้ป่วยใหม่ (ยังไม่มีประวัติเดิม)")
    return " | ".join(parts) if parts else None


def build_sbar(
    metadata: dict[str, Any],
    *,
    department_th: str,
    rerouted: bool = False,
    chief_complaint: str | None = None,
    illness_note: str | None = None,
) -> dict[str, str | None]:
    """Build the seven SBAR fields from a session's metadata.

    ``chief_complaint`` / ``illness_note`` are the nurse's signed-off
    overrides; each falls back to the engine's value when not provided.

    The seven output keys are the HOSPITAL's names, fixed by their contract —
    do not rename them. Ours map in as: chief complaint → ``situation``,
    illness note → ``assessment_problem``. ``recommend`` has no narrative
    field of ours behind it; it is derived from the department and response
    time.
    """
    classification = metadata.get("triage_classification") or {}
    vitals = metadata.get("vitals") or {}
    history = metadata.get("patient_history") or {}
    visit = metadata.get("visit") or {}

    # S — what is happening now. Our chief complaint.
    situation = _clean(chief_complaint) or _clean(classification.get("symptoms_summary"))
    age = visit.get("age_years")
    if situation and age:
        situation = f"{situation} (อายุ {age} ปี)"

    # B — what the destination needs to know about this patient already.
    background = _history_line(history)

    # A — objective findings, and the triage level. The level belongs here
    # unless/until the hospital gives us a real acuity field (change request 1).
    assessment_parts = [p for p in (_vitals_line(vitals),) if p]
    level, label = classification.get("level"), _clean(classification.get("label"))
    if level:
        assessment_parts.append(
            f"ระดับคัดกรอง {level}" + (f" ({label})" if label else "")
        )
    if classification.get("pain_score") is not None:
        assessment_parts.append(f"ระดับความเจ็บปวด {classification['pain_score']}/10")
    assessment = " | ".join(assessment_parts) or None

    # A(problem) — our illness note, plus the manual citations that justify
    # the routing, so the destination can check our work.
    problem_parts = [p for p in (_clean(illness_note),) if p]
    reasons = disposition_reason_texts(classification, prefer_thai=True)
    if reasons:
        problem_parts.extend(reasons)
    elif not problem_parts:
        # key_reason may be English; only used when there is nothing better.
        problem_parts = [p for p in (_clean(classification.get("key_reason")),) if p]
    assessment_problem = " | ".join(problem_parts) or None

    # R — where the patient is going and how fast.
    recommend_parts = [f"ส่งต่อ {department_th}"]
    if response_time := _clean(classification.get("response_time")):
        recommend_parts.append(f"ควรได้รับการตรวจภายใน {response_time}")
    if rerouted:
        # iMed has no `rerouted` flag, so it can only be said in prose.
        recommend_parts.append("พยาบาลปรับแผนกจากที่ระบบแนะนำ")
    recommend = " | ".join(recommend_parts)

    # D — how to find the full record on our side.
    doc_parts = []
    if slip := _clean(metadata.get("slip_code")):
        doc_parts.append(f"รหัสสลิป {slip}")
    if follow_up := _clean(metadata.get("patient_follow_up")):
        doc_parts.append(f"ผู้ป่วยฝากถาม: {follow_up}")
    documentation = " | ".join(doc_parts) or None

    return {
        "situation": situation,
        "background": background,
        "assessment": assessment,
        "assessment_problem": assessment_problem,
        # Deliberately never auto-filled: deciding what equipment to prepare is
        # a clinical judgement our system does not make. The nurse fills it.
        "assessment_equipment": None,
        "recommend": recommend,
        "documentation": documentation,
    }
