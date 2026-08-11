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
    # question), and measurements whose value never arrived or was rejected as
    # implausible, get exactly ONE repeat; when not provided, membership in
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
        # Safety-critical: a red flag is resolved only when EVERY finding it
        # covers is known. A compound question ("fever or vomiting with the
        # urinary symptoms?", "spreading redness, pus, or fever?") is NOT
        # answered by the one finding the patient happened to volunteer — the
        # rule that escalates usually needs the other one (wound infection
        # signs + fever = level 2), and treating a present-but-harmless finding
        # as an answer silently deleted that question from the interview.
        # A present finding that really does fire a level-1/2 rule never
        # reaches here: the completeness gate disposes first.
        # Unknown findings get exactly ONE re-ask — a garbled voice turn or an
        # unmappable bare "yes" must not silently skip a stroke/meningitis
        # check — then two asks give up so extraction failures can't loop.
        states = [inputs.findings.get(fid) for fid in question.finding_ids]
        if all(s is not None for s in states):
            return True
        return _ask_count(question, inputs) >= 2
    if question.kind == "measurement":
        # Checked BEFORE the asked-once rule so a reading that never arrived —
        # or arrived physiologically impossible and was rejected — gets exactly
        # ONE more attempt. Two asks then give up, so a patient who keeps
        # typing nonsense can't loop the interview; the vital is left missing
        # and flagged for the nurse instead.
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
        return _ask_count(question, inputs) >= 2
    if question.id in inputs.asked_question_ids:
        return True
    if question.kind == "intake":
        # Ask "what brings you in?" only until a chief complaint is established.
        return inputs.complaint_category is not None
    if question.kind == "age":
        return inputs.age_known
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
        # those fires at most twice (one ask plus one re-ask for a missing or
        # implausible value), so this hold extends the flow by at most
        # 2 × len(pre_disposition_questions) turns.
        return not _unresolved_pre_disposition(criteria, inputs)
    # Hold disposition while weight/height (etc.) remain unasked.
    if _unresolved_pre_disposition(criteria, inputs):
        return False
    if not red_flags_resolved(criteria, inputs):
        return False
    template = get_template(criteria, inputs.complaint_category)
    # Hold while the template's measurements (BP, temp) remain unasked — the
    # "vitals always recorded" rule. Without this, a complaint sentence that
    # already fills the minimum OLDCARTS slots disposes straight past the BP
    # question, and a hypertensive crisis walks through unmeasured. Terminates
    # like pre-disposition: each measurement resolves after at most two asks,
    # and the budget-exhaust branch above still ends the flow regardless.
    if any(not _is_resolved(q, inputs) for q in template.questions
           if q.kind == "measurement"):
        return False
    min_slots = template.min_slots_by_level.get(provisional_level, 3)
    if len(inputs.answered_slots) >= min_slots:
        return True
    return next_question(criteria, inputs) is None


def confirm_question_for(
    criteria: ScreeningCriteria, finding_id: str, category: str | None = None
) -> QuestionTemplate:
    """The question that confirms one extraction-sourced critical finding.

    Prefer a nurse-authored question that checks EXACTLY this finding
    (verbatim wording, and a yes/no maps unambiguously); synthesize a plain
    yes/no confirm from the catalog labels otherwise — a multi-finding
    template question can't confirm one specific finding. Confirm questions
    are never LLM-paraphrased.

    Only the SESSION's own template (plus the universal questions) is
    searched. An unrelated template's wording can name the wrong body part —
    "is something stuck in your EAR?" asked of a fish bone in the throat —
    and a truthful "no" would erase a real level-2 finding. The synthesized
    fallback is category-neutral, so it is always safe.
    """

    template = get_template(criteria, category)
    for q in [*template.questions, *criteria.universal_questions]:
        if q.kind in ("red_flag", "associated") and q.finding_ids == [finding_id]:
            return q

    entry = criteria.finding_catalog.get(finding_id)
    label_en = entry.label_en if entry else finding_id
    label_th = entry.label_th if entry else finding_id
    return QuestionTemplate(
        id=f"confirm_{finding_id}",
        kind="red_flag",
        finding_ids=[finding_id],
        text_en=f"Just to make sure I understood — do you have this right now: {label_en}?",
        text_th=f"ขอยืนยันให้แน่ใจนะคะ ตอนนี้คุณมีอาการนี้ใช่ไหมคะ: {label_th}",
    )
