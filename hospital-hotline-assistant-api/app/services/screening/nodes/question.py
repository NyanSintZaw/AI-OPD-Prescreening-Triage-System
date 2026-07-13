"""Question node: deterministic selection, optional LLM paraphrase."""

from __future__ import annotations

import logging
from time import perf_counter

from langchain_core.messages import HumanMessage

from ..rules.question_policy import InterviewInputs, next_question
from ..state import TurnOutput
from ..validator import validate_reply
from .base import GraphDeps, GraphState, ainvoke_with_timeout

logger = logging.getLogger(__name__)

# Only conversational-comfort questions may be paraphrased; red-flag, scale,
# and age questions are always rendered with nurse-approved wording.
PARAPHRASABLE_KINDS = {"slot", "associated"}

_PARAPHRASE_PROMPT = {
    "en": (
        "You are a warm, calm hospital screening assistant speaking English. "
        "Rephrase the following screening question conversationally, preserving its exact "
        "clinical meaning. Ask exactly ONE question, one or two short sentences, no lists, "
        "no medical jargon, and never mention triage levels or diagnoses.\n"
        "Patient context: {context}\nQuestion to rephrase: {question}"
    ),
    "th": (
        "คุณเป็นผู้ช่วยคัดกรองของโรงพยาบาลที่พูดจาอบอุ่นและใจเย็น พูดภาษาไทยเท่านั้น "
        "ช่วยเรียบเรียงคำถามคัดกรองต่อไปนี้ให้เป็นธรรมชาติ โดยคงความหมายทางคลินิกเดิมทุกประการ "
        "ถามเพียงหนึ่งคำถาม ความยาวหนึ่งถึงสองประโยคสั้น ๆ ห้ามใช้ศัพท์แพทย์ "
        "และห้ามพูดถึงระดับการคัดกรองหรือการวินิจฉัย\n"
        "บริบทผู้ป่วย: {context}\nคำถามที่ต้องเรียบเรียง: {question}"
    ),
}


def interview_inputs(state, deps: GraphDeps) -> InterviewInputs:
    return InterviewInputs(
        complaint_category=state.complaint_category,
        findings=state.finding_states(),
        answered_slots=state.answered_slots(),
        asked_question_ids=frozenset(state.asked_question_ids),
        age_known=state.age_years is not None,
        measured_vitals=frozenset(state.vitals),
        questions_asked=state.questions_asked,
        question_budget=deps.question_budget,
    )


def make_question_node(deps: GraphDeps):
    async def question(graph_state: GraphState) -> GraphState:
        state = graph_state["s"]
        criteria = graph_state["criteria"]
        audit = graph_state.get("audit") or []

        selected = next_question(criteria, interview_inputs(state, deps))
        if selected is None:
            # Router guarantees a question exists; guard anyway.
            state.phase = "history"
            return {"s": state, "audit": audit}

        verbatim = selected.text_en if state.language == "en" else selected.text_th
        reply = verbatim

        if deps.model is not None and selected.kind in PARAPHRASABLE_KINDS:
            context = state.chief_complaint or "-"
            prompt = _PARAPHRASE_PROMPT[state.language].format(
                context=context, question=verbatim,
            )
            started = perf_counter()
            ok = False
            try:
                response = await ainvoke_with_timeout(
                    deps.model, [HumanMessage(content=prompt)], deps.model_timeout_s
                )
                candidate = (response.content or "").strip() if isinstance(response.content, str) else ""
                if candidate and not validate_reply(candidate, language=state.language):
                    reply = candidate
                    ok = True
            except Exception:
                logger.exception("question paraphrase failed; using verbatim template")
            audit.append({
                "call_site": "question",
                "latency_ms": int((perf_counter() - started) * 1000),
                "ok": ok,
                "question_id": selected.id,
            })

        state.asked_question_ids.append(selected.id)
        state.questions_asked += 1
        state.pending_question_id = selected.id
        # A measurement question asks the booth to take a reading (e.g.
        # temperature); the transport layer pops a numeric input for it.
        state.awaiting_measurement = selected.vital if selected.kind == "measurement" else None
        state.phase = "history"
        return {
            "s": state,
            "audit": audit,
            "output": TurnOutput(reply=reply, awaiting_measurement=state.awaiting_measurement),
        }

    return question
