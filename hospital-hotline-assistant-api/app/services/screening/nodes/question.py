"""Question node: deterministic selection, optional LLM paraphrase.

The paraphrase call is structured: it returns the reworded question PLUS 3–4
short tappable answer choices matched to that wording. Both are validated;
any failure falls back to the verbatim template + deterministic chips.
"""

from __future__ import annotations

import logging
from collections import Counter
from time import perf_counter

from pydantic import BaseModel, Field

from .. import templates
from ..rules.criteria_models import QuestionTemplate
from ..rules.question_policy import InterviewInputs, next_question
from ..state import TurnOutput
from ..validator import validate_reply
from .base import GraphDeps, GraphState, ainvoke_with_timeout

logger = logging.getLogger(__name__)

# Only conversational-comfort questions may be paraphrased; red-flag, scale,
# and age questions are always rendered with nurse-approved wording.
PARAPHRASABLE_KINDS = {"slot", "associated"}

_MAX_OPTION_CHARS = 40
_MAX_OPTIONS = 4


class PhrasedQuestion(BaseModel):
    """Structured paraphrase: the reworded question + tappable answers."""

    question: str = Field(description="The rephrased screening question")
    options: list[str] = Field(
        default_factory=list,
        description=(
            "3 or 4 short, mutually distinct answer choices the patient "
            "could tap, in the same language as the question"
        ),
    )


_PARAPHRASE_PROMPT = {
    "en": (
        "You are a warm, calm hospital screening assistant speaking English. "
        "Rephrase the following screening question conversationally, preserving its exact "
        "clinical meaning. Ask exactly ONE question, one or two short sentences, no lists, "
        "no medical jargon, and never mention triage levels or diagnoses.\n"
        "Do NOT re-ask anything already answered.\n"
        "Also provide 3 or 4 short answer choices (max 30 characters each) the patient "
        "could tap to answer, in English, mutually distinct, covering the most likely "
        "answers; never include diagnoses, levels, or medication.\n"
        "Patient context: {context}\n"
        "Already answered — do not re-ask: {known}\n"
        "Question to rephrase: {question}"
    ),
    "th": (
        "คุณเป็นผู้ช่วยคัดกรองของโรงพยาบาลที่พูดจาอบอุ่นและใจเย็น พูดภาษาไทยเท่านั้น "
        "ช่วยเรียบเรียงคำถามคัดกรองต่อไปนี้ให้เป็นธรรมชาติ โดยคงความหมายทางคลินิกเดิมทุกประการ "
        "ถามเพียงหนึ่งคำถาม ความยาวหนึ่งถึงสองประโยคสั้น ๆ ห้ามใช้ศัพท์แพทย์ "
        "และห้ามพูดถึงระดับการคัดกรองหรือการวินิจฉัย\n"
        "ห้ามถามซ้ำสิ่งที่ผู้ป่วยตอบไปแล้ว\n"
        "พร้อมกันนี้ให้เสนอตัวเลือกคำตอบสั้น ๆ 3 หรือ 4 ตัวเลือก (ไม่เกิน 30 ตัวอักษรต่อตัวเลือก) "
        "เป็นภาษาไทย แตกต่างกันชัดเจน ครอบคลุมคำตอบที่เป็นไปได้ "
        "ห้ามมีการวินิจฉัย ระดับการคัดกรอง หรือชื่อยา\n"
        "บริบทผู้ป่วย: {context}\n"
        "ข้อมูลที่ผู้ป่วยตอบแล้ว ห้ามถามซ้ำ: {known}\n"
        "คำถามที่ต้องเรียบเรียง: {question}"
    ),
}


def interview_inputs(state, deps: GraphDeps) -> InterviewInputs:
    return InterviewInputs(
        complaint_category=state.complaint_category,
        findings=state.finding_states(),
        answered_slots=state.answered_slots(),
        asked_question_ids=frozenset(state.asked_question_ids),
        age_known=state.age_years is not None,
        age_years=state.age_years,
        measured_vitals=frozenset(state.vitals),
        questions_asked=state.questions_asked,
        question_budget=deps.question_budget,
        # duplicates appear when a red flag is re-asked (list, not set)
        ask_counts=Counter(state.asked_question_ids),
    )


def known_answers_line(state) -> str:
    """Summarize what the patient already told us, so the paraphrase never
    re-asks it (the demo showed onset re-asked as duration)."""

    parts = [f"{slot}: {answer}" for slot, answer in state.slots.items()]
    present = [fid for fid, f in state.findings.items() if f.state == "present"]
    if present:
        parts.append("reported: " + ", ".join(present))
    return "; ".join(parts) or "-"


def localize_options(
    question: QuestionTemplate, language: str, criteria=None
) -> list[dict[str, str]]:
    """Deterministic reply chips (authored/default) — used for verbatim kinds
    and as the fallback when the structured paraphrase yields no usable options.
    Measurement questions never get chips."""

    if question.kind == "measurement":
        return []
    if question.options:
        return [
            {
                "id": opt.id,
                "label": opt.text_th if language == "th" else opt.text_en,
            }
            for opt in question.options
        ]
    if question.kind in ("red_flag", "associated") or question.id == "uq_breathing":
        # A compound red flag ("confusion, trouble breathing, or stiff neck?")
        # answered with a bare Yes is unmappable — a live demo undertriaged a
        # yes-to-meningitis-signs to level 4 because no finding was recorded.
        # Offer one chip per finding plus "None of these" so a tap is always
        # unambiguous.
        # uq_breathing's findings are severity grades of one symptom — plain
        # Yes/No reads naturally and extraction maps a bare yes to the milder
        # grade; per-finding chips are for questions bundling DISTINCT symptoms.
        if (
            question.kind == "red_flag"
            and question.id != "uq_breathing"
            and criteria is not None
            and len(question.finding_ids) > 1
        ):
            chips: list[dict[str, str]] = []
            for fid in question.finding_ids:
                fdef = criteria.finding_catalog.get(fid)
                if fdef is None:
                    break
                chips.append({
                    "id": fid,
                    "label": fdef.label_th if language == "th" else fdef.label_en,
                })
            else:
                chips.append({
                    "id": "none_of_these",
                    "label": templates.NONE_OF_THESE.get(
                        language, templates.NONE_OF_THESE["en"]
                    ),
                })
                return chips
        return list(templates.YES_NO_OPTIONS.get(language, templates.YES_NO_OPTIONS["en"]))
    if question.kind == "scale":
        return [{"id": str(i), "label": str(i)} for i in range(11)]
    return []


def _accept_options(raw: list[str], language: str) -> list[dict[str, str]]:
    """Keep LLM options only when they're clean, short, and 2–4 distinct."""

    cleaned: list[str] = []
    for item in raw:
        label = (item or "").strip()
        if not label or len(label) > _MAX_OPTION_CHARS:
            continue
        if validate_reply(label, language=language):
            continue  # validator violation (level/diagnosis leak) — drop all
        if label.lower() in (c.lower() for c in cleaned):
            continue
        cleaned.append(label)
        if len(cleaned) == _MAX_OPTIONS:
            break
    if len(cleaned) < 2:
        return []
    return [{"id": f"opt_{i + 1}", "label": label} for i, label in enumerate(cleaned)]


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
        reply_options = localize_options(selected, state.language, criteria)

        if deps.model is not None and selected.kind in PARAPHRASABLE_KINDS:
            prompt = _PARAPHRASE_PROMPT[state.language].format(
                context=state.chief_complaint or "-",
                known=known_answers_line(state),
                question=verbatim,
            )
            started = perf_counter()
            ok = False
            try:
                structured = deps.model.with_structured_output(PhrasedQuestion)
                phrased = await ainvoke_with_timeout(
                    structured, prompt, deps.model_timeout_s
                )
                candidate = (phrased.question or "").strip()
                if candidate and not validate_reply(candidate, language=state.language):
                    reply = candidate
                    ok = True
                    llm_options = _accept_options(phrased.options, state.language)
                    if llm_options:
                        reply_options = llm_options
            except Exception:
                logger.exception("question paraphrase failed; using verbatim template")
            audit.append({
                "call_site": "question",
                "latency_ms": int((perf_counter() - started) * 1000),
                "ok": ok,
                "question_id": selected.id,
            })

        state.asked_question_ids.append(selected.id)
        # Measurement requests don't count against the interview budget: they
        # are booth actions, not questions the patient must think about, and
        # asked_question_ids already guarantees each fires at most once. The
        # budget must stay a cap on cognitive burden, not on readings.
        if selected.kind != "measurement":
            state.questions_asked += 1
        state.pending_question_id = selected.id
        # A measurement question asks the booth to take a reading (e.g.
        # temperature); the transport layer pops a numeric input for it.
        state.awaiting_measurement = selected.vital if selected.kind == "measurement" else None
        state.phase = "history"
        return {
            "s": state,
            "audit": audit,
            "output": TurnOutput(
                reply=reply,
                awaiting_measurement=state.awaiting_measurement,
                reply_options=reply_options,
            ),
        }

    return question
