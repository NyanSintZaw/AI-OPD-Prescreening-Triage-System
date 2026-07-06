"""Shared graph state and dependencies for the screening graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel

from ..rules.criteria_models import ScreeningCriteria
from ..state import ScreeningState, TurnOutput


class GraphState(TypedDict, total=False):
    s: ScreeningState
    criteria: ScreeningCriteria
    user_text: str
    contact_turn: bool
    output: TurnOutput
    # per-turn audit records appended by nodes: {call_site, latency_ms, ok, ...}
    audit: list[dict[str, Any]]


@dataclass
class GraphDeps:
    """Stable, session-independent dependencies bound into node closures."""

    model: BaseChatModel | None
    question_budget: int = 8
    # department_code -> {"en": name, "th": name}; used for reply templates
    department_names: dict[str, dict[str, str]] = field(default_factory=dict)
    # department_code -> list of display names for the consistency validator
    validator_department_names: dict[str, list[str]] = field(default_factory=dict)
