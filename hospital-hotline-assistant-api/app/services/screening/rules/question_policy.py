"""Deterministic next-question selection.

The interview order is nurse-controlled data, not model behavior: universal
life-threat checks first, then the complaint template's questions by their
``priority`` field (red flags are conventionally numbered first), then
``pre_disposition_questions`` (e.g. weight/height) last. The LLM only
verbalizes the selected question — it never chooses what to ask.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    age_years: float | None              # numeric age when known (for min_age_years gates)
    measured_vitals: frozenset[str]      # canonical vital keys present (sbp, temp, …)
    questions_asked: int
    question_budget: int
    # How many times each question has been asked. Red flags whose findings
    # stay unknown after one ask (garbled STT, bare "yes" on a compound
    # question) get exactly ONE repeat; when not provided, membership in
    # asked_question_ids counts as exhausted (the old no-repeat behavior).
    ask_counts: Mapping[str, int] = field(default_factory=dict)


def get_template(criteria: ScreeningCriteria, category: str | None) -> ComplaintTemplate:
    wanted = category or GENERIC_CATEGORY
    by_category = {t.category: t for t in criteria.complaint_templates}
    return by_category.get(wanted) or by_category[GENERIC_CATEGORY]


def _any_finding_present(question: QuestionTemplate, inputs: InterviewInputs) -> bool:
    return any(inputs.findings.get(fid) == "present" for fid in question.finding_ids)


def _all_findings_present(question: QuestionTemplate, inputs: InterviewInputs) -> bool:
    return all(inputs.findings.get(fid) == "present" for fid in question.finding_ids)


def _ask_count(question: QuestionTemplate, inputs: InterviewInputs) -> int:
    if inputs.ask_counts:
        return inputs.ask_counts.get(question.id, 0)
    # No counts wired (older callers/tests): treat one ask as exhausted.
    return 2 if question.id in inputs.asked_question_ids else 0


def _is_resolved(question: QuestionTemplate, inputs: InterviewInputs) -> bool:
    """A question is resolved when asking it would gain no new information."""

    if question.kind == "red_flag":
        # Safety-critical: an unanswered red flag is re-asked ONCE — a garbled
        # voice turn or an unmappable bare "yes" must not silently skip a
        # stroke/meningitis check. Two unanswered asks then give up, so
        # extraction failures can't loop the interview. Any PRESENT finding
        # resolves it immediately (the flag has fired; disposition reacts).
        states = [inputs.findings.get(fid) for fid in question.finding_ids]
        if any(s == "present" for s in states):
            return True
        if all(s is not None for s in states):
            return True
        return _ask_count(question, inputs) >= 2
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
        # Age-gated measurements (e.g. BP in ENT for age ≥ 60 only): skip when
        # age is unknown or below the threshold.
        if question.min_age_years is not None:
            if inputs.age_years is None or inputs.age_years < question.min_age_years:
                return True
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
    # associated: unresolved only if at least one target finding is unknown
    return all(fid in inputs.findings for fid in question.finding_ids)


def _ordered_questions(
    criteria: ScreeningCriteria, template: ComplaintTemplate
) -> Iterable[QuestionTemplate]:
    yield from sorted(criteria.universal_questions, key=lambda q: q.priority)
    yield from sorted(template.questions, key=lambda q: q.priority)
    # Universal wrap-up questions (booth measurements like weight/height)
    # deliberately come after every complaint-specific question.
    yield from sorted(criteria.pre_disposition_questions, key=lambda q: q.priority)


def _unresolved_pre_disposition(
    criteria: ScreeningCriteria, inputs: InterviewInputs
) -> bool:
    return any(
        not _is_resolved(q, inputs) for q in criteria.pre_disposition_questions
    )


def next_question(
    criteria: ScreeningCriteria, inputs: InterviewInputs
) -> QuestionTemplate | None:
    """Deterministically pick the next question, or None when nothing useful
    remains to ask. Budget enforcement is the completeness gate's job —
    except that once the budget is spent, only wrap-up measurements (which
    fire at most once and don't count against the budget) remain eligible."""

    if inputs.questions_asked >= inputs.question_budget:
        for question in sorted(
            criteria.pre_disposition_questions, key=lambda q: q.priority
        ):
            if not _is_resolved(question, inputs):
                return question
        return None
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
    question remains. Pre-disposition measurements (weight/height) hold
    completeness until resolved, except on emergency dispose or budget exhaust.
    """

    if provisional_level <= 2:
        return True
    if inputs.questions_asked >= inputs.question_budget:
        # Budget caps interview questions, not wrap-up measurements: each of
        # those fires at most once (asked ids resolve them), so this hold
        # extends the flow by at most len(pre_disposition_questions) turns.
        return not _unresolved_pre_disposition(criteria, inputs)
    # Hold disposition while weight/height (etc.) remain unasked.
    if _unresolved_pre_disposition(criteria, inputs):
        return False
    if not red_flags_resolved(criteria, inputs):
        return False
    template = get_template(criteria, inputs.complaint_category)
    min_slots = template.min_slots_by_level.get(provisional_level, 3)
    if len(inputs.answered_slots) >= min_slots:
        return True
    return next_question(criteria, inputs) is None
