"""Shared graph state and dependencies for the screening graph."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel

from ..rules.criteria_models import ScreeningCriteria
from ..state import ScreeningState, TurnOutput


async def ainvoke_with_timeout(runnable: Any, payload: Any, timeout_s: float) -> Any:
    """Invoke a LangChain runnable with a hard wall-clock cap.

    The Vertex/Gemini gRPC call has no client deadline by default, so a stalled
    response hangs the whole turn (and the voice call) forever. ``wait_for``
    cancels the stuck call and raises ``TimeoutError`` — an ``Exception`` the
    node try/except paths already catch and degrade from (verbatim question,
    template explanation, extraction retry/escalate). Provider-agnostic, so it
    also protects the openai_compatible backend.
    """
    return await asyncio.wait_for(runnable.ainvoke(payload), timeout=timeout_s)


class GraphState(TypedDict, total=False):
    s: ScreeningState
    criteria: ScreeningCriteria
    user_text: str
    output: TurnOutput
    # per-turn audit records appended by nodes: {call_site, latency_ms, ok, ...}
    audit: list[dict[str, Any]]


@dataclass
class GraphDeps:
    """Stable, session-independent dependencies bound into node closures."""

    model: BaseChatModel | None
    question_budget: int = 8
    # hard per-LLM-call wall-clock cap (seconds); prevents a stalled Gemini
    # gRPC call from hanging a turn / voice call forever.
    model_timeout_s: float = 30.0
    # department_code -> {"en": name, "th": name}; used for reply templates
    department_names: dict[str, dict[str, str]] = field(default_factory=dict)
    # department_code -> list of display names for the consistency validator
    validator_department_names: dict[str, list[str]] = field(default_factory=dict)
    # optional async retriever over the nurse-uploaded manual, used to ground
    # the routing explanation with citations (query -> passage text)
    rag_search: Callable[[str], Awaitable[str]] | None = None
