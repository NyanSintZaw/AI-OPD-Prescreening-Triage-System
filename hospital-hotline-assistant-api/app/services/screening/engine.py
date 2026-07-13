"""ScreeningTriageEngine — the deterministic engine behind TriageService.

Implements the existing ``TriageEngine`` protocol so TriageService,
persistence, the contact-flow state machine, and the frontend all work
unchanged. Emits the same event vocabulary as the legacy ADK runner
(``delta`` / ``classified`` / ``done``) and the same classification/contact
dict shapes.
"""

from __future__ import annotations

import logging
import re
from typing import Any, AsyncIterator

from app.services.ai.triage_models import TriageDecision

from . import templates
from .graph import build_screening_graph
from .nodes.base import GraphDeps
from .persistence import InMemoryStateStore, StateStore
from .state import ScreeningState, TurnOutput
from .vitals import normalize_vitals

logger = logging.getLogger(__name__)

_MARKER_LINE = re.compile(r"^\[[A-Z_]+:[^\]]*\]\s*$", re.MULTILINE)

_LEVEL_TO_SEVERITY: dict[int, str] = {
    1: "emergency",
    2: "emergency",
    3: "urgent",
    4: "general",
    5: "general",
}


def _default_department_names() -> dict[str, dict[str, str]]:
    return {code: dict(names) for code, names in templates.DEPARTMENT_NAMES.items()}


class ScreeningTriageEngine:
    def __init__(
        self,
        *,
        model,
        store: StateStore | None = None,
        question_budget: int = 8,
        prompt_version: str = "v1",
        model_label: str = "screening:unknown",
        department_names: dict[str, dict[str, str]] | None = None,
        rag_search=None,
    ) -> None:
        self._store = store or InMemoryStateStore()
        self._prompt_version = prompt_version
        self._model_label = model_label
        names = department_names or _default_department_names()
        deps = GraphDeps(
            model=model,
            question_budget=question_budget,
            department_names=names,
            validator_department_names={
                code: [n for n in lang_names.values() if n]
                for code, lang_names in names.items()
            },
            rag_search=rag_search,
        )
        self._graph = build_screening_graph(deps)

    # -- TriageEngine protocol -------------------------------------------------

    async def ensure_session(
        self, *, session_id: str, language: str, input_mode: str
    ) -> None:
        state = await self._store.load(session_id)
        if state is None:
            state = self._new_state(session_id, language, input_mode)
            await self._store.save(state)

    async def run_turn(
        self,
        *,
        session_id: str,
        language: str,
        input_mode: str,
        content: str,
        schedule_context: str | None = None,
        turn_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._execute(
            session_id=session_id,
            language=language,
            input_mode=input_mode,
            content=content,
            turn_context=turn_context,
        )

    async def run_turn_stream(
        self,
        *,
        session_id: str,
        language: str,
        input_mode: str,
        content: str,
        schedule_context: str | None = None,
        turn_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        result = await self._execute(
            session_id=session_id,
            language=language,
            input_mode=input_mode,
            content=content,
            turn_context=turn_context,
        )
        yield {"type": "delta", "text": result["reply"]}
        if result["classification"].get("classified") is True:
            yield {"type": "classified", "classification": result["classification"]}
        yield {
            "type": "done",
            "reply": result["reply"],
            "classification": result["classification"],
            "input_mode": input_mode,
            "model_name": result.get("model_name"),
        }

    def decision_from_classification(self, classification: dict[str, Any]) -> TriageDecision:
        level = classification.get("level")
        esi_level = level if isinstance(level, int) else None
        severity = _LEVEL_TO_SEVERITY.get(esi_level, "unknown")
        department_code = classification.get("department_code")
        return TriageDecision(
            esi_level=esi_level,
            severity_level=severity,
            opd_department_code=str(department_code) if department_code else None,
            key_reason=classification.get("key_reason"),
            symptoms_summary=classification.get("symptoms_summary"),
            needs_emergency_contact=False,
            classification=classification,
        )

    # -- internals ---------------------------------------------------------------

    @staticmethod
    def _apply_turn_context(
        state: ScreeningState, turn_context: dict[str, Any] | None
    ) -> None:
        """Merge booth-supplied age + measured vitals into the state before
        the graph runs, so the red-flag gate evaluates real numbers (e.g. a
        cuff reading of 84/53 fires the danger-vitals rule deterministically).

        Objective vitals/age override prior values; the LLM never sees or
        decides these, it only extracts symptoms.
        """
        if not turn_context:
            return
        age = turn_context.get("age_years")
        if isinstance(age, (int, float)) and age >= 0:
            state.age_years = float(age)
            state.age_asked = True  # never ask — the HIS gave it to us
        vitals = normalize_vitals(turn_context.get("vitals"))
        if vitals:
            state.vitals.update(vitals)

    def _new_state(self, session_id: str, language: str, input_mode: str) -> ScreeningState:
        return ScreeningState(
            session_id=session_id,
            language="en" if language == "en" else "th",
            mode="voice" if input_mode == "voice" else "text",
            prompt_version=self._prompt_version,
        )

    @staticmethod
    def _parse_content(content: str) -> str:
        return _MARKER_LINE.sub("", content).strip()

    async def _execute(
        self,
        *,
        session_id: str,
        language: str,
        input_mode: str,
        content: str,
        turn_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        user_text = self._parse_content(content)
        state = await self._store.load(session_id)
        if state is None:
            state = self._new_state(session_id, language, input_mode)
        if language in ("en", "th"):
            state.language = language  # session language is locked upstream
        state.mode = "voice" if input_mode == "voice" else "text"
        self._apply_turn_context(state, turn_context)

        version_id, criteria = await self._store.get_criteria(state.criteria_version_id)
        state.criteria_version_id = version_id
        state.turn_count += 1

        result = await self._graph.ainvoke({
            "s": state,
            "criteria": criteria,
            "user_text": user_text,
            "audit": [],
        })
        state = result["s"]
        output: TurnOutput = result.get("output") or TurnOutput(
            reply=templates.ESCALATION[state.language], escalated=True,
        )
        await self._store.save(state)
        await self._store.write_audit(
            session_id=session_id,
            turn_no=state.turn_count,
            entries=result.get("audit") or [],
            model_name=self._model_label,
            prompt_version=state.prompt_version,
            criteria_version_id=state.criteria_version_id,
        )

        return {
            "reply": output.reply,
            "classification": output.classification or {},
            "input_mode": input_mode,
            "model_name": self._model_label,
            "escalated": output.escalated,
            "audit": result.get("audit") or [],
        }


def make_triage_engine(settings, pool=None):
    """Build the deterministic screening engine (the only engine)."""

    from .model_adapter import build_chat_model
    from .persistence import PostgresStateStore

    model = None
    if getattr(settings, "google_ai_enabled", False) or (
        settings.screening_model_provider == "openai_compatible"
    ):
        model = build_chat_model(settings)
    store = PostgresStateStore(pool) if pool is not None else InMemoryStateStore()
    rag_search = None
    try:
        from app.services.ai.rag_query import search_triage_manual

        rag_search = search_triage_manual
    except Exception:  # pragma: no cover - RAG stack optional in dev
        logger.warning("RAG grounding unavailable for screening engine")
    return ScreeningTriageEngine(
        model=model,
        store=store,
        question_budget=getattr(settings, "screening_question_budget", 8),
        prompt_version=getattr(settings, "screening_prompt_version", "v1"),
        model_label=(
            f"screening:{settings.screening_model_provider}:"
            f"{settings.screening_model_name}"
        ),
        rag_search=rag_search,
    )
