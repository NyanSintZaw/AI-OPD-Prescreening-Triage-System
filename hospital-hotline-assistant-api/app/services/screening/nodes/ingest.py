"""Ingest node: LLM structured extraction of the patient's message."""

from __future__ import annotations

import logging
import re
from time import perf_counter

from ..extraction import ExtractionResult, build_extraction_prompt
from ..rules.question_policy import get_template
from ..state import OLDCARTS_SLOTS, Finding
from .base import GraphDeps, GraphState, ainvoke_with_timeout

logger = logging.getLogger(__name__)

MAX_EXTRACTION_FAILURES = 2

# Sequence of affirmation tokens; Thai polite particles join without spaces
# ("ใช่ค่ะ" = ใช่ + ค่ะ), so the separator is optional.
_AFF_TOKEN = r"(?:yes|yeah|yep|sure|ok|okay|ใช่|มี|ครับผม|ครับ|ค่ะ|คะ)"
_BARE_AFFIRMATION = re.compile(
    rf"^\s*{_AFF_TOKEN}(?:[\s,.!]*{_AFF_TOKEN})*[\s,.!]*$",
    re.IGNORECASE,
)


def _pending_question(state, criteria):
    if not state.pending_question_id:
        return None
    template = get_template(criteria, state.complaint_category)
    questions = [
        *criteria.universal_questions,
        *template.questions,
        *criteria.pre_disposition_questions,
    ]
    for question in questions:
        if question.id == state.pending_question_id:
            return question
    return None


def _pending_question_text(state, criteria) -> str | None:
    question = _pending_question(state, criteria)
    if question is None:
        return None
    return question.text_en if state.language == "en" else question.text_th


def strip_ambiguous_affirmation(result: ExtractionResult, pending, user_text: str) -> None:
    """A bare "yes" to a compound red flag cannot say WHICH bundled symptom is
    present — models mark them ALL (observed live: one Yes recorded confusion,
    dyspnea AND stiff_neck as present). Drop those updates deterministically so
    the policy re-asks the question with one chip per finding. uq_breathing is
    exempt: its findings are severity grades and the mildest-grade rule applies.
    """

    if (
        pending is None
        or pending.kind != "red_flag"
        or pending.id == "uq_breathing"
        or len(pending.finding_ids) <= 1
        or not _BARE_AFFIRMATION.match(user_text)
    ):
        return
    ambiguous = set(pending.finding_ids)
    result.finding_updates = [
        u for u in result.finding_updates if u.id not in ambiguous
    ]


def _closest_category(raw: str, known: set[str]) -> str | None:
    """Deterministically map a near-miss category id to a known one.

    Models sometimes merge ids (gemini-3.1-flash-lite reliably returns
    'ear_nose_throat' for a sore-throat+cough message). Score known ids by
    token overlap and accept only a unique best match — an ambiguous or
    zero-overlap id stays unmapped, so the intake question fires instead.
    """
    tokens = set(raw.lower().replace("-", "_").split("_"))
    scores = sorted(
        ((len(tokens & set(k.split("_"))), k) for k in known), reverse=True
    )
    if not scores or scores[0][0] == 0:
        return None
    if len(scores) > 1 and scores[1][0] == scores[0][0]:
        return None  # tie — don't guess
    return scores[0][1]


def _apply(state, criteria, result: ExtractionResult) -> None:
    turn = state.turn_count
    if result.chief_complaint and not state.chief_complaint:
        state.chief_complaint = result.chief_complaint
    if result.complaint_category:
        known = {t.category for t in criteria.complaint_templates}
        # routing-only categories (no bespoke template) are also legal
        known |= {e.complaint_category for e in criteria.routing_table}
        category = (
            result.complaint_category
            if result.complaint_category in known
            else _closest_category(result.complaint_category, known)
        )
        if category and not state.complaint_category:
            state.complaint_category = category

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

        # Clear any prior measurement request; the question node re-sets it
        # if it asks for another reading this turn. (turn_context has already
        # merged a supplied reading into state.vitals before the graph ran.)
        state.awaiting_measurement = None

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
                result = await ainvoke_with_timeout(structured, prompt, deps.model_timeout_s)
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
        strip_ambiguous_affirmation(
            result, _pending_question(state, criteria), user_text
        )
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
