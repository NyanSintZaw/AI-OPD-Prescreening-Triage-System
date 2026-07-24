"""Map structured HN patient history into screening risk-factor findings.

Mirrors ``vitals.apply_objective_findings``: booth/HIS structured data beats
chat extraction so chronic conditions, smoking, etc. are present on turn 1
without the patient having to restate them.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from .state import Finding

# Free-text "none / ไม่มี" answers should not fire risk findings.
_NONE_RE = re.compile(
    r"^\s*(?:none|no|n/?a|nil|ไม่มี|ไม่เคย|ไม่สูบ|ไม่ดื่ม|-|—|–)\s*$",
    re.IGNORECASE,
)

# Keyword → finding_id for chronic_conditions / family_history free text.
# Patterns tolerate lay phrasing and word order ("my blood pressure has been
# high"), the common misspelling stem ("hyperten…"), and Thai equivalents —
# patients write however they speak (live E2E finding, July 22).
_CHRONIC_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"diabet|high\s+blood\s+sugar|blood\s+sugar[^.;,]{0,30}high|"
            r"เบาหวาน|น้ำตาล(?:ในเลือด)?สูง",
            re.I,
        ),
        "diabetes_history",
    ),
    (
        re.compile(
            r"hyperten|\bhbp\b|"
            r"high\s+blood\s+pressure|blood\s+pressure[^.;,]{0,40}high|"
            r"ความดัน",
            re.I,
        ),
        "hypertension_history",
    ),
    (re.compile(r"heart|coronary|หัวใจ|เส้นเลือดหัวใจ", re.I), "heart_disease_history"),
    (re.compile(r"copd|emphysema|ถุงลม|ปอดอุดกั้น|chronic\s+lung", re.I), "copd_history"),
]

# Per-substance negations: "ไม่เคยสูบ ไม่ดื่ม" / "non-smoker" / "no alcohol"
# must NOT stamp the risk finding. Deliberately per-substance, not per-field,
# so "ไม่สูบ แต่ดื่มหนัก" still stamps alcohol_use. A quit/former habit
# ("เลิกสูบแล้ว", "quit smoking") still counts — an ex-smoker remains a risk
# factor and the verbatim detail rides on the finding value for the nurse.
_SMOKE_NEG_RE = re.compile(
    r"non[- ]?smok|never\s+smoked?|don'?t\s+smoke|no\s+smoking|"
    r"ไม่(?:เคย)?สูบ", re.I,
)
_ALCOHOL_NEG_RE = re.compile(
    r"non[- ]?drink|never\s+drinks?|don'?t\s+drink|no\s+alcohol|"
    r"ไม่(?:เคย|ค่อย)?ดื่ม", re.I,
)
_ALLERGY_NEG_RE = re.compile(
    r"no\s+(?:known\s+)?allerg|none\s+known|never\s+had\s+aller|"
    r"ไม่(?:มี(?:ประวัติ)?|เคย)?แพ้", re.I,
)

_SMOKE_RE = re.compile(
    r"smok|cigarette|tobacco|สูบ|บุหรี่", re.I
)
_ALCOHOL_RE = re.compile(
    r"alcohol|drink|beer|wine|เหล้า|สุรา|แอลกอฮอล์|ดื่ม", re.I
)


def _has_content(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    return not _NONE_RE.match(text)


def _set_present(state, finding_id: str, value: str | None = None) -> None:
    existing = state.findings.get(finding_id)
    if existing is not None and existing.state == "present":
        return
    state.findings[finding_id] = Finding(
        state="present",
        value=value,
        source_turn=state.turn_count,
    )


def history_dict_from_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize session metadata patient_history for turn_context."""
    if not metadata:
        return {}
    raw = metadata.get("patient_history")
    if not isinstance(raw, dict):
        return {}
    return dict(raw)


def apply_history_findings(state, patient_history: Mapping[str, Any] | None) -> None:
    """Stamp risk-factor findings from structured HN / intake history."""
    if not patient_history:
        return

    smoking_alcohol = patient_history.get("smoking_alcohol")
    if _has_content(smoking_alcohol):
        text = str(smoking_alcohol)
        if _SMOKE_RE.search(text) and not _SMOKE_NEG_RE.search(text):
            _set_present(state, "smoking", text)
        if _ALCOHOL_RE.search(text) and not _ALCOHOL_NEG_RE.search(text):
            _set_present(state, "alcohol_use", text)

    allergies = patient_history.get("allergies")
    if _has_content(allergies) and not _ALLERGY_NEG_RE.search(str(allergies)):
        _set_present(state, "allergy_history", str(allergies))

    past = patient_history.get("past_surgeries")
    if _has_content(past):
        _set_present(state, "past_surgery_history", str(past))

    family = patient_history.get("family_history")
    if _has_content(family):
        _set_present(state, "family_history_chronic", str(family))
        for pattern, finding_id in _CHRONIC_KEYWORDS:
            if pattern.search(str(family)):
                # Family history of a specific chronic disease is still the
                # family_history_chronic finding; do not mark the patient's
                # own chronic condition findings from family text alone.
                pass

    chronic = patient_history.get("chronic_conditions")
    if _has_content(chronic):
        text = str(chronic)
        matched = False
        for pattern, finding_id in _CHRONIC_KEYWORDS:
            if pattern.search(text):
                _set_present(state, finding_id, text)
                matched = True
        if not matched:
            # Unknown chronic label — still a risk signal via allergy-style
            # catch-all is not ideal; leave as no finding rather than guess.
            pass
