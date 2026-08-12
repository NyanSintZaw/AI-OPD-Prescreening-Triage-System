"""Nurse-readable projection of a screening criteria document (read-only).

The stored document is ~7,500 lines of JSON with a condition AST — correct for
the engine, unreadable for the head nurse who has to sign off on it. This module
flattens it into the few things a nurse asks: which questions each complaint
asks, what the finding ids mean, and which rules can force a triage level —
each with the manual clause it came from and its condition rendered as text.

Pure functions over the raw JSONB payload: no DB, no pydantic parsing (a
document that fails validation must still be viewable).
"""

from __future__ import annotations

from app.services.screening.templates import DEPARTMENT_NAMES


def _dept_names(code: str | None) -> dict[str, str | None]:
    """Bilingual display names beside every department code.

    A nurse reading “opd_ent” has to translate in her head; the booth already
    holds the human names it speaks to patients, so the rule book shows the
    same ones. An unknown code yields None rather than a guess — unmapped IS
    the information there."""
    entry = DEPARTMENT_NAMES.get(code or "")
    return {
        "department_name_en": entry.get("en") if entry else None,
        "department_name_th": entry.get("th") if entry else None,
    }

from typing import Any

_OPS = {"lt": "<", "le": "≤", "gt": ">", "ge": "≥", "eq": "="}

# Display names for vitals; anything else falls back to the raw id upper-cased.
_VITALS = {
    "sbp": "SBP", "dbp": "DBP", "map": "MAP", "hr": "HR", "rr": "RR",
    "spo2": "SpO₂", "temp": "Temp", "pain_score": "Pain", "age_years": "Age",
    "distress_score": "Distress", "weight": "Weight", "height": "Height",
}

_WORDS = {
    "en": {"and": " AND ", "or": " OR ", "not": "NO ", "none": "—"},
    "th": {"and": " และ ", "or": " หรือ ", "not": "ไม่มี", "none": "—"},
}


def render_condition(
    condition: Any,
    labels: dict[str, str] | None = None,
    lang: str = "en",
    _depth: int = 0,
) -> str:
    """Render a condition AST as one readable line.

    ``labels`` maps finding id → display label; ids without a label (or with
    no map at all) render as the raw id, so a broken document still renders.

        {"all_of": [{"finding_id": "fever"},
                    {"any_of": [{"finding_id": "confusion"},
                                {"finding_id": "stiff_neck"}]}]}
        → "Fever AND (Confusion OR Neck stiffness)"
    """

    words = _WORDS.get(lang, _WORDS["en"])
    if not isinstance(condition, dict):
        return words["none"]
    labels = labels or {}

    text = ""
    composite = 0
    if condition.get("finding_id"):
        fid = condition["finding_id"]
        text = labels.get(fid) or fid
        if condition.get("state") == "absent":
            text = f"{words['not']}{text}"
    elif condition.get("vital"):
        vital = condition["vital"]
        op = _OPS.get(condition.get("op") or "", condition.get("op") or "?")
        text = f"{_VITALS.get(vital, vital.upper())} {op} {condition.get('value', '?')}"
    else:
        for key, joiner in (("all_of", words["and"]), ("any_of", words["or"])):
            children = condition.get(key) or []
            if children:
                composite = len(children)
                text = joiner.join(
                    render_condition(child, labels, lang, _depth + 1) for child in children
                )
                break

    if not text:
        return words["none"]
    if _depth > 0 and composite > 1:
        text = f"({text})"
    if condition.get("age_band"):
        text = f"[{condition['age_band']}] {text}"
    return text


def _is_placeholder(citation: str) -> bool:
    """Citations carry ⚠️ PLACEHOLDER when the clause awaits hospital sign-off."""
    return "PLACEHOLDER" in (citation or "").upper()


def _question(raw: dict) -> dict:
    return {
        "id": raw.get("id"),
        "kind": raw.get("kind"),
        "slot": raw.get("slot"),
        "vital": raw.get("vital"),
        "min_age_years": raw.get("min_age_years"),
        "finding_ids": raw.get("finding_ids") or [],
        "text_en": raw.get("text_en", ""),
        "text_th": raw.get("text_th", ""),
        "options": [
            {"id": o.get("id"), "text_en": o.get("text_en", ""), "text_th": o.get("text_th", "")}
            for o in (raw.get("options") or [])
        ],
        "citation": raw.get("citation", ""),
        "placeholder": _is_placeholder(raw.get("citation", "")),
    }


def _rule(raw: dict, group: str, labels: dict[str, str], labels_th: dict[str, str]) -> dict:
    citation = raw.get("citation", "")
    return {
        "id": raw.get("id"),
        "group": group,
        "label_en": raw.get("label_en", ""),
        "label_th": raw.get("label_th", ""),
        "condition_en": render_condition(raw.get("condition"), labels, "en"),
        "condition_th": render_condition(raw.get("condition"), labels_th, "th"),
        "level": raw.get("level"),
        "min_level": raw.get("min_level") or raw.get("force_min_level"),
        "department_code": raw.get("department_code"),
        **_dept_names(raw.get("department_code")),
        "citation": citation,
        "placeholder": _is_placeholder(citation),
    }


def build_criteria_view(payload: dict, meta: dict | None = None) -> dict:
    """Flatten a raw criteria document into the nurse-facing read model."""

    catalog = payload.get("finding_catalog") or {}
    labels = {fid: (d.get("label_en") or fid) for fid, d in catalog.items()}
    labels_th = {fid: (d.get("label_th") or d.get("label_en") or fid) for fid, d in catalog.items()}

    def rules_of(key: str, group: str) -> list[dict]:
        return [_rule(r, group, labels, labels_th) for r in (payload.get(key) or [])]

    rules = [
        *rules_of("level1_criteria", "level1"),
        *rules_of("danger_vitals", "danger_vital"),
        *rules_of("fast_tracks", "fast_track"),
        *rules_of("department_rules", "department_rule"),
    ]
    # Triage tuples have no condition AST — findings_all (+ any risk factor)
    # is their condition, so render it the same way rules render theirs.
    for tup in payload.get("triage_tuples") or []:
        condition = {"all_of": [{"finding_id": f} for f in (tup.get("findings_all") or [])]}
        risk = tup.get("risk_factors_any") or []
        if risk:
            condition["all_of"].append({"any_of": [{"finding_id": f} for f in risk]})
        rules.append(
            _rule({**tup, "condition": condition}, "triage_tuple", labels, labels_th)
        )

    routing = []
    for entry in payload.get("routing_table") or []:
        conditions = entry.get("specialty_conditions") or []
        routing.append({
            "complaint_category": entry.get("complaint_category"),
            "department_code": entry.get("department_code"),
            **_dept_names(entry.get("department_code")),
            "fallback_department_code": entry.get("fallback_department_code"),
            "condition_en": (
                render_condition({"any_of": conditions}, labels, "en") if conditions else ""
            ),
            "condition_th": (
                render_condition({"any_of": conditions}, labels_th, "th") if conditions else ""
            ),
            "citation": entry.get("citation", ""),
            "placeholder": _is_placeholder(entry.get("citation", "")),
        })

    return {
        **(meta or {}),
        "source_standards": payload.get("source_standards") or [],
        "complaint_templates": [
            {
                "category": tpl.get("category"),
                "label_en": tpl.get("label_en", ""),
                "label_th": tpl.get("label_th", ""),
                "keywords_en": tpl.get("keywords_en") or [],
                "keywords_th": tpl.get("keywords_th") or [],
                "questions": [_question(q) for q in (tpl.get("questions") or [])],
            }
            for tpl in (payload.get("complaint_templates") or [])
        ],
        "universal_questions": [_question(q) for q in (payload.get("universal_questions") or [])],
        "pre_disposition_questions": [
            _question(q) for q in (payload.get("pre_disposition_questions") or [])
        ],
        "findings": [
            {
                "id": fid,
                "label_en": d.get("label_en", ""),
                "label_th": d.get("label_th", ""),
                "synonyms_en": d.get("synonyms_en") or [],
                "synonyms_th": d.get("synonyms_th") or [],
                "is_risk_factor": bool(d.get("is_risk_factor")),
            }
            for fid, d in sorted(catalog.items())
        ],
        "rules": rules,
        "routing": routing,
    }
