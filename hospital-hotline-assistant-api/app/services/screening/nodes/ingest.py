"""Ingest node: LLM structured extraction of the patient's message."""

from __future__ import annotations

import logging
from time import perf_counter

from ..extraction import ExtractionResult, build_extraction_prompt
from ..rules.question_policy import get_template
from ..state import OLDCARTS_SLOTS, Finding
from .base import GraphDeps, GraphState

logger = logging.getLogger(__name__)

MAX_EXTRACTION_FAILURES = 2


def _pending_question_text(state, criteria) -> str | None:
    if not state.pending_question_id:
        return None
    template = get_template(criteria, state.complaint_category)
    for question in [*criteria.universal_questions, *template.questions]:
        if question.id == state.pending_question_id:
            return question.text_en if state.language == "en" else question.text_th
    return None


def _apply(state, criteria, result: ExtractionResult) -> None:
    turn = state.turn_count
    if result.chief_complaint and not state.chief_complaint:
        state.chief_complaint = result.chief_complaint
    if result.complaint_category:
        known = {t.category for t in criteria.complaint_templates}
        # routing-only categories (no bespoke template) are also legal
        known |= {e.complaint_category for e in criteria.routing_table}
        if result.complaint_category in known and not state.complaint_category:
            state.complaint_category = result.complaint_category

    for update in result.finding_updates:
        if update.id in criteria.finding_catalog:
            state.findings[update.id] = Finding(
                state=update.state, value=update.value, source_turn=turn,
            )
    for slot, value in result.slot_updates.items():
        if slot in OLDCARTS_SLOTS and value and str(value).strip():
            state.slots[slot] = str(value).strip()

    if result.age_years is not None and 0 <= result.age_years <= 120:
        state.age_years = float(result.age_years)
    if result.pain_score is not None:
        state.vitals["pain_score"] = float(result.pain_score)
        state.slots.setdefault("severity", str(result.pain_score))
    if result.distress_score is not None:
        state.vitals["distress_score"] = float(result.distress_score)
        state.slots.setdefault("severity", str(result.distress_score))
    if result.temperature_c is not None and 30 <= result.temperature_c <= 45:
        state.vitals["temp"] = float(result.temperature_c)


def make_ingest_node(deps: GraphDeps):
    async def ingest(graph_state: GraphState) -> GraphState:
        state = graph_state["s"]
        criteria = graph_state["criteria"]
        user_text = graph_state["user_text"]
        audit = graph_state.get("audit") or []

        if deps.model is None:
            # No model configured — cannot extract; escalate to a nurse.
            state.extraction_failures = MAX_EXTRACTION_FAILURES
            state.phase = "escalated_to_nurse"
            return {"s": state, "audit": audit}

        prompt = build_extraction_prompt(
            criteria, state, user_text, _pending_question_text(state, criteria),
        )
        structured = deps.model.with_structured_output(ExtractionResult)
        started = perf_counter()
        result: ExtractionResult | None = None
        for attempt in (1, 2):
            try:
                result = await structured.ainvoke(prompt)
                break
            except Exception:
                logger.exception("extraction attempt %d failed", attempt)
        latency_ms = int((perf_counter() - started) * 1000)
        audit.append({
            "call_site": "extraction", "latency_ms": latency_ms, "ok": result is not None,
        })

        if result is None:
            state.extraction_failures += 1
            if state.extraction_failures >= MAX_EXTRACTION_FAILURES:
                state.phase = "escalated_to_nurse"
            return {"s": state, "audit": audit}

        state.extraction_failures = 0
        _apply(state, criteria, result)
        if result.wants_human:
            state.phase = "escalated_to_nurse"
        else:
            # The pending question was addressed (even if vaguely) — it is
            # resolved by being asked; never repeat it.
            state.pending_question_id = None
            if state.phase == "intake":
                state.phase = "history"
        return {"s": state, "audit": audit}

    return ingest
