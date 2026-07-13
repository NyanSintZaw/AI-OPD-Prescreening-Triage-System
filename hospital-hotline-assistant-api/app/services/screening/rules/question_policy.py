"""Deterministic next-question selection.

The interview order is nurse-controlled data, not model behavior: universal
life-threat checks first, then the complaint template's questions by their
``priority`` field (red flags are conventionally numbered first). The LLM only
verbalizes the selected question — it never chooses what to ask.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .criteria_models import ComplaintTemplate, QuestionTemplate, ScreeningCriteria

GENERIC_CATEGORY = "generic"


@dataclass(frozen=True)
class InterviewInputs:
    complaint_category: str | None
    findings: Mapping[str, str]          # finding id -> "present" | "absent"
    answered_slots: frozenset[str]       # OLDCARTS slots already filled
    asked_question_ids: frozenset[str]
    age_known: bool
    measured_vitals: frozenset[str]      # canonical vital keys present (sbp, temp, …)
    questions_asked: int
    question_budget: int


def get_template(criteria: ScreeningCriteria, category: str | None) -> ComplaintTemplate:
    wanted = category or GENERIC_CATEGORY
    by_category = {t.category: t for t in criteria.complaint_templates}
    return by_category.get(wanted) or by_category[GENERIC_CATEGORY]


def _any_finding_present(question: QuestionTemplate, inputs: InterviewInputs) -> bool:
    return any(inputs.findings.get(fid) == "present" for fid in question.finding_ids)


def _all_findings_present(question: QuestionTemplate, inputs: InterviewInputs) -> bool:
    return all(inputs.findings.get(fid) == "present" for fid in question.finding_ids)


def _is_resolved(question: QuestionTemplate, inputs: InterviewInputs) -> bool:
    """A question is resolved when asking it would gain no new information."""

    if question.id in inputs.asked_question_ids:
        return True
    if question.kind == "intake":
        # Ask "what brings you in?" only until a chief complaint is established.
        return inputs.complaint_category is not None
    if question.kind == "age":
        return inputs.age_known
    if question.kind == "measurement":
        if question.vital in inputs.measured_vitals:
            return True  # already measured
        # Only request the reading when its gating findings are present
        # (e.g. temperature only once fever is reported).
        if question.finding_ids and not _all_findings_present(question, inputs):
            return True
        return False
    if question.kind == "slot":
        return question.slot in inputs.answered_slots
    if question.kind == "scale":
        # Skip a symptom-specific scale when its finding isn't present
        # (e.g. don't ask "how hard is it to breathe?" without dyspnea).
        if question.finding_ids and not _any_finding_present(question, inputs):
            return True
        return "severity" in inputs.answered_slots
    # red_flag / associated: unresolved only if at least one target is unknown
    return all(fid in inputs.findings for fid in question.finding_ids)


def _ordered_questions(
    criteria: ScreeningCriteria, template: ComplaintTemplate
) -> Iterable[QuestionTemplate]:
    yield from sorted(criteria.universal_questions, key=lambda q: q.priority)
    yield from sorted(template.questions, key=lambda q: q.priority)


def next_question(
    criteria: ScreeningCriteria, inputs: InterviewInputs
) -> QuestionTemplate | None:
    """Deterministically pick the next question, or None when nothing useful
    remains to ask. Budget enforcement is the completeness gate's job."""

    template = get_template(criteria, inputs.complaint_category)
    for question in _ordered_questions(criteria, template):
        if not _is_resolved(question, inputs):
            return question
    return None


def red_flags_resolved(criteria: ScreeningCriteria, inputs: InterviewInputs) -> bool:
    template = get_template(criteria, inputs.complaint_category)
    return all(
        _is_resolved(q, inputs)
        for q in _ordered_questions(criteria, template)
        if q.kind == "red_flag"
    )


def is_interview_complete(
    criteria: ScreeningCriteria,
    inputs: InterviewInputs,
    provisional_level: int,
) -> bool:
    """Completeness gate run after every extraction turn.

    Levels 1–2 dispose immediately; otherwise the interview continues until
    red-flag questions are resolved and the template's minimum OLDCARTS slots
    for the provisional level are filled, the budget is spent, or no useful
    question remains.
    """

    if provisional_level <= 2:
        return True
    if inputs.questions_asked >= inputs.question_budget:
        return True
    if not red_flags_resolved(criteria, inputs):
        return False
    template = get_template(criteria, inputs.complaint_category)
    min_slots = template.min_slots_by_level.get(provisional_level, 3)
    if len(inputs.answered_slots) >= min_slots:
        return True
    return next_question(criteria, inputs) is None
