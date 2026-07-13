"""LLM structured extraction of one patient utterance.

The model's only job here is mapping natural language (th/en) onto the
bounded finding vocabulary and OLDCARTS slots — it makes no clinical
decisions. Output is schema-constrained via ``with_structured_output``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .rules.criteria_models import ScreeningCriteria
from .rules.question_policy import get_template
from .state import ScreeningState


class FindingUpdate(BaseModel):
    """One finding the patient's message resolves."""

    id: str = Field(description="Canonical finding id from the provided catalog")
    state: Literal["present", "absent"] = Field(
        description="present if the patient confirms it, absent if they deny it"
    )
    value: str | None = Field(
        default=None, description="Optional detail, e.g. '3 days' or 'left side'"
    )


class ExtractionResult(BaseModel):
    """Structured reading of a single patient message."""

    chief_complaint: str | None = Field(
        default=None,
        description="Patient's main problem in their own words, only when newly stated",
    )
    complaint_category: str | None = Field(
        default=None,
        description="Best matching complaint category from the provided list, or null",
    )
    finding_updates: list[FindingUpdate] = Field(default_factory=list)
    slot_updates: dict[str, str] = Field(
        default_factory=dict,
        description="OLDCARTS slots this message answers (onset, location, duration, "
        "character, aggravating, relieving, timing, severity) mapped to the answer text",
    )
    age_years: float | None = Field(
        default=None, description="Patient age in years when stated (0.5 = 6 months)"
    )
    pain_score: int | None = Field(
        default=None, ge=0, le=10, description="0-10 pain score when stated"
    )
    distress_score: int | None = Field(
        default=None, ge=0, le=10, description="0-10 breathing difficulty score when stated"
    )
    temperature_c: float | None = Field(
        default=None, description="Body temperature in Celsius when stated"
    )
    is_question_to_assistant: bool = Field(
        default=False,
        description="True when the message is a question to the assistant rather than "
        "an answer about symptoms",
    )
    wants_human: bool = Field(
        default=False, description="True when the patient asks for a human/nurse"
    )


def _catalog_lines(criteria: ScreeningCriteria, state: ScreeningState) -> list[str]:
    """Bounded finding vocabulary for the prompt: the active template's
    red-flag/associated targets plus every finding referenced by rules that
    could fire next, with bilingual labels and synonyms."""

    template = get_template(criteria, state.complaint_category)
    wanted: set[str] = set(template.associated_finding_ids)
    for question in [*criteria.universal_questions, *template.questions]:
        wanted.update(question.finding_ids)
    # Findings referenced by tuples/rules keyed to already-present findings
    present = {fid for fid, f in state.findings.items() if f.state == "present"}
    for tup in criteria.triage_tuples:
        if present & set(tup.findings_all):
            wanted.update(tup.findings_all)
            wanted.update(tup.risk_factors_any)
    # Always allow the critical universals so an unprompted "he collapsed and
    # isn't breathing" is never dropped.
    wanted.update({
        "cardiac_arrest", "unresponsive", "seizure_now", "dyspnea",
        "severe_respiratory_distress", "chest_pain", "active_bleeding",
        "blue_lips", "pale_cold_sweaty", "suicidal_ideation", "pregnancy",
    })

    lines = []
    for fid in sorted(wanted):
        entry = criteria.finding_catalog.get(fid)
        if entry is None:
            continue
        synonyms = ", ".join([*entry.synonyms_en, *entry.synonyms_th][:6])
        line = f"- {fid}: {entry.label_en} / {entry.label_th}"
        if synonyms:
            line += f" (also: {synonyms})"
        lines.append(line)
    return lines


def build_extraction_prompt(
    criteria: ScreeningCriteria,
    state: ScreeningState,
    user_text: str,
    pending_question_text: str | None,
) -> str:
    categories = ", ".join(t.category for t in criteria.complaint_templates)
    catalog = "\n".join(_catalog_lines(criteria, state))
    context_lines = []
    if state.chief_complaint:
        context_lines.append(f"Chief complaint so far: {state.chief_complaint}")
    if pending_question_text:
        context_lines.append(f"The assistant just asked: {pending_question_text}")
    context = "\n".join(context_lines) or "This is the first message."

    return f"""You are a clinical intake scribe for a Thai hospital. Read ONE patient message
(Thai or English) and extract ONLY what the patient actually said into the
structured schema. Never guess, never diagnose, never infer findings that were
not stated. If the message answers the assistant's pending question, record
that answer (as finding updates with state "absent" when the patient denies,
or slot/score updates).

Context:
{context}

Allowed complaint categories (copy ONE id verbatim — never invent or combine ids): {categories}

Finding catalog (use ONLY these ids):
{catalog}

Rules:
- A denial ("no", "ไม่มีค่ะ") of the pending question's findings -> those finding ids with state "absent".
- Numbers 0-10 answering a pain/breathing question -> pain_score or distress_score.
- Ages like "6 เดือน" -> age_years 0.5.
- complaint_category: whenever the patient states any symptom, pick the SINGLE
  closest category from the allowed list. If more than one could fit (e.g.
  sore throat + cough), pick the one matching the symptom they said first.
  Use null only when no category fits at all (e.g. a greeting or a question).
- wants_human=true only when they explicitly ask for a person/nurse/staff.

Patient message:
{user_text}"""
