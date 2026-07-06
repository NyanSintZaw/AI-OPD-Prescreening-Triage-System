"""Validate patient-facing replies before display (SRS F50).

Blocks triage-level/color disclosure, diagnosis/prescription language,
language mismatch, and department inconsistency. The caller escalates:
regenerate once → deterministic template → nurse fallback.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str


# --- level / color disclosure -------------------------------------------------

_LEVEL_PATTERNS = [
    re.compile(r"\b(?:triage\s+)?level\s*[1-5]\b", re.IGNORECASE),
    re.compile(r"\b(?:esi|moph)\b", re.IGNORECASE),
    re.compile(r"ระดับ(?:ความรุนแรง|การคัดกรอง)?\s*(?:ที่)?\s*[1-5๑-๕]"),
    re.compile(r"เลเวล\s*[1-5๑-๕]"),
]

# Triage colors only flag when tied to triage context to avoid banning the
# words entirely ("red rash" is fine, "triage color red" / "สีแดง (ฉุกเฉิน)" is not).
_COLOR_CONTEXT = re.compile(
    r"(?:triage|urgency|priority|classified|classification|ประเภท|คัดกรอง|ความเร่งด่วน)"
    r"[^.\n]{0,40}?"
    r"(?:red|orange|yellow|green|white|สีแดง|สีส้ม|สีเหลือง|สีเขียว|สีขาว)"
    r"|(?:red|orange|yellow|green|white|สีแดง|สีส้ม|สีเหลือง|สีเขียว|สีขาว)"
    r"[^.\n]{0,25}?(?:triage|urgency|priority|ประเภท|คัดกรอง|ความเร่งด่วน)",
    re.IGNORECASE,
)

# --- diagnosis / prescription -------------------------------------------------

_DIAGNOSIS_PATTERNS = [
    re.compile(r"\byou (?:likely |probably |definitely |may )?have\b (?!to\b)", re.IGNORECASE),
    re.compile(r"\bdiagnos(?:is|ed|e)\b", re.IGNORECASE),
    re.compile(r"คุณ(?:น่าจะ|อาจจะ|คงจะ)?(?:เป็นโรค|ป่วยเป็น)"),
    re.compile(r"วินิจฉัยว่า"),
]

_PRESCRIPTION_PATTERNS = [
    re.compile(r"\b(?:take|use)\s+\d+\s*(?:mg|mcg|g|ml|tablets?|pills?|capsules?)\b", re.IGNORECASE),
    re.compile(r"(?:กิน|ทาน|รับประทาน)ยา[^\s]*\s*\d+\s*(?:มก|มิลลิกรัม|เม็ด|ช้อน)"),
    re.compile(r"\b(?:paracetamol|ibuprofen|amoxicillin|aspirin|antibiotic)s?\s+\d+", re.IGNORECASE),
]

_THAI_CHARS = re.compile(r"[฀-๿]")
_LATIN_CHARS = re.compile(r"[A-Za-z]")


def _thai_ratio(text: str) -> float:
    thai = len(_THAI_CHARS.findall(text))
    latin = len(_LATIN_CHARS.findall(text))
    total = thai + latin
    return thai / total if total else 0.0


def validate_reply(
    reply: str,
    *,
    language: str,
    department_code: str | None = None,
    department_names: dict[str, list[str]] | None = None,
    is_emergency: bool = False,
) -> list[Violation]:
    """Return violations for a candidate patient-facing reply.

    ``department_names`` maps department_code -> display names (en+th) so the
    consistency check can detect the reply naming a *different* department
    than the validated disposition.
    """

    violations: list[Violation] = []
    text = reply.strip()
    if not text:
        return [Violation("empty", "empty reply")]

    for pattern in _LEVEL_PATTERNS:
        match = pattern.search(text)
        if match:
            violations.append(Violation("level_disclosure", match.group(0)))
            break
    color_match = _COLOR_CONTEXT.search(text)
    if color_match:
        violations.append(Violation("color_disclosure", color_match.group(0)))

    for pattern in _DIAGNOSIS_PATTERNS:
        match = pattern.search(text)
        if match:
            violations.append(Violation("diagnosis", match.group(0)))
            break
    for pattern in _PRESCRIPTION_PATTERNS:
        match = pattern.search(text)
        if match:
            violations.append(Violation("prescription", match.group(0)))
            break

    ratio = _thai_ratio(text)
    if language == "th" and ratio < 0.5:
        violations.append(Violation("language_mismatch", f"thai ratio {ratio:.2f} in th session"))
    elif language == "en" and ratio > 0.5:
        violations.append(Violation("language_mismatch", f"thai ratio {ratio:.2f} in en session"))

    if department_code and department_names:
        lowered = text.lower()
        if is_emergency:
            er_names = [n.lower() for n in department_names.get("emergency", [])]
            if er_names and not any(n in lowered for n in er_names):
                violations.append(Violation(
                    "consistency", "emergency disposition but reply does not direct to ER",
                ))
        for code, names in department_names.items():
            if code == department_code or code == "emergency":
                continue
            for name in names:
                if name and name.lower() in lowered:
                    violations.append(Violation(
                        "consistency", f"reply names other department: {name}",
                    ))
                    break

    return violations
