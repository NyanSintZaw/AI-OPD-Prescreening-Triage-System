from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MatchResult:
    id: str
    name: str
    priority: int
    confidence: float
    reason: str
    severity_override: str | None = None
    alert_message: str | None = None
    department_id: str | None = None
    keywords: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScaleOverrideResult:
    severity: str | None
    reason: str | None


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _condition_matches(text: str, condition: dict[str, Any]) -> bool:
    all_terms = [str(v).lower() for v in condition.get("all", []) if str(v).strip()]
    any_terms = [str(v).lower() for v in condition.get("any", []) if str(v).strip()]

    if all_terms and not all(term in text for term in all_terms):
        return False
    if any_terms and not any(term in text for term in any_terms):
        return False
    return bool(all_terms or any_terms)


def _keywords_match(text: str, keywords: list[str]) -> bool:
    return any(keyword.lower() in text for keyword in keywords if keyword.strip())


def _normalize_flag(value: Any) -> str:
    return str(value).strip().lower().replace(" ", "_").replace("-", "_")


def _normalize_score(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        score = int(value)
    except (TypeError, ValueError):
        return None
    return score if 0 <= score <= 10 else None


def evaluate_scale_override(
    classification: dict[str, Any],
    current_severity: str,
) -> ScaleOverrideResult:
    """Escalate acuity from collected pain/distress scale fields.

    This helper never downgrades an existing emergency. Scores only become
    emergency when paired with critical signs or high-risk context; severe
    isolated pain/distress is urgent rather than automatic emergency.
    """

    if current_severity == "emergency":
        return ScaleOverrideResult(severity=None, reason=None)

    pain_score = _normalize_score(classification.get("pain_score"))
    distress_score = _normalize_score(classification.get("distress_score"))
    pain_location = _normalize_flag(classification.get("pain_location") or "")
    distress_type = _normalize_flag(classification.get("distress_type") or "")
    raw_red_flags = classification.get("red_flags") or []
    red_flag_items = raw_red_flags if isinstance(raw_red_flags, list) else [raw_red_flags]
    red_flags = {
        _normalize_flag(flag)
        for flag in red_flag_items
        if str(flag).strip()
    }

    critical_flags = {
        "blue_lips",
        "unable_to_breathe",
        "confusion",
        "unresponsive",
        "severe_bleeding",
    }
    if red_flags & critical_flags:
        return ScaleOverrideResult(
            severity="emergency",
            reason="Critical red flag reported with pain/distress assessment",
        )

    breathing_flags = {
        "breathing_difficulty",
        "shortness_of_breath",
        "chest_tightness",
        "unable_to_speak_full_sentences",
        "unable_to_breathe",
    }
    if distress_score is not None and distress_score >= 8:
        if red_flags & breathing_flags or distress_type in breathing_flags:
            return ScaleOverrideResult(
                severity="emergency",
                reason="Severe breathing distress score with respiratory red flags",
            )

    high_risk_pain_locations = {
        "chest",
        "head",
        "headache",
        "abdomen",
        "abdominal",
        "pregnancy",
        "trauma",
        "major_trauma",
        "back_neuro",
    }
    high_risk_pain_flags = {
        "breathing_difficulty",
        "shortness_of_breath",
        "neuro",
        "neuro_symptoms",
        "stroke_symptoms",
        "fainting",
        "confusion",
        "pregnancy",
        "major_trauma",
        "severe_bleeding",
    }
    if pain_score is not None and pain_score >= 8:
        if (
            pain_location in high_risk_pain_locations
            or red_flags & high_risk_pain_flags
        ):
            return ScaleOverrideResult(
                severity="emergency",
                reason="Severe pain score with high-risk context",
            )

    if pain_score is not None and pain_score >= 7:
        return ScaleOverrideResult(
            severity="urgent",
            reason="Severe pain score without emergency red flags",
        )
    if distress_score is not None and distress_score >= 7:
        return ScaleOverrideResult(
            severity="urgent",
            reason="Severe distress score without emergency red flags",
        )

    return ScaleOverrideResult(severity=None, reason=None)


def evaluate_emergency_triggers(
    text: str,
    triggers: list[dict[str, Any]],
    language: str = "en",
) -> list[MatchResult]:
    normalized = _normalize(text)
    matches: list[MatchResult] = []

    for trigger in triggers:
        condition = trigger.get("condition_json") or {}
        keywords = trigger.get("trigger_keywords") or []
        matched = _condition_matches(normalized, condition) or _keywords_match(normalized, keywords)
        if not matched:
            continue

        alert_message = trigger.get("alert_message_en") or ""
        if language == "th" and trigger.get("alert_message_th"):
            alert_message = trigger["alert_message_th"]

        matches.append(
            MatchResult(
                id=str(trigger["id"]),
                name=str(trigger["trigger_name"]),
                priority=int(trigger.get("priority", 999)),
                confidence=0.9,
                reason=f"Matched emergency trigger: {trigger['trigger_name']}",
                severity_override="emergency",
                alert_message=alert_message,
                keywords=[str(k) for k in (trigger.get("trigger_keywords") or []) if str(k).strip()],
            )
        )

    matches.sort(key=lambda item: item.priority)
    return matches


def evaluate_routing_rules(text: str, rules: list[dict[str, Any]]) -> list[MatchResult]:
    normalized = _normalize(text)
    matches: list[MatchResult] = []

    for rule in rules:
        condition = rule.get("condition_json") or {}
        keywords = rule.get("symptom_keywords") or []
        matched = _condition_matches(normalized, condition) or _keywords_match(normalized, keywords)
        if not matched:
            continue

        matches.append(
            MatchResult(
                id=str(rule["id"]),
                name=str(rule["rule_name"]),
                priority=int(rule.get("priority", 999)),
                confidence=0.75,
                reason=f"Matched routing rule: {rule['rule_name']}",
                severity_override=rule.get("severity_override"),
                department_id=str(rule["department_id"]),
                keywords=[str(k) for k in (rule.get("symptom_keywords") or []) if str(k).strip()],
            )
        )

    matches.sort(key=lambda item: item.priority)
    return matches
