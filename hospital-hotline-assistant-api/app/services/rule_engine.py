from __future__ import annotations

from dataclasses import dataclass
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
            )
        )

    matches.sort(key=lambda item: item.priority)
    return matches
