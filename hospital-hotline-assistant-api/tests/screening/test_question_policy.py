"""Question-policy tests: deterministic order, no repeats, completeness gate."""

import pytest

from app.services.screening.rules.question_policy import (
    InterviewInputs,
    is_interview_complete,
    next_question,
)


def inputs(
    category="chest_pain",
    findings=None,
    answered_slots=(),
    asked=(),
    age_known=True,
    questions_asked=0,
    budget=8,
):
    return InterviewInputs(
        complaint_category=category,
        findings=findings or {},
        answered_slots=frozenset(answered_slots),
        asked_question_ids=frozenset(asked),
        age_known=age_known,
        questions_asked=questions_asked,
        question_budget=budget,
    )


def test_age_asked_first_when_unknown(criteria):
    q = next_question(criteria, inputs(age_known=False))
    assert q is not None and q.id == "uq_age"


def test_universal_breathing_before_template(criteria):
    q = next_question(criteria, inputs())
    assert q.id == "uq_breathing"


def test_red_flags_before_slots(criteria):
    # breathing already resolved -> first chest-pain red flag
    q = next_question(criteria, inputs(findings={"dyspnea": "absent", "severe_respiratory_distress": "absent"}))
    assert q.id == "cp_radiating"
    assert q.kind == "red_flag"


def test_partial_red_flag_answer_still_asks(criteria):
    # only one of the two breathing findings known -> still unresolved
    q = next_question(criteria, inputs(findings={"dyspnea": "absent"}))
    assert q.id == "uq_breathing"


def test_slots_in_template_priority_order(criteria):
    findings = {
        "dyspnea": "absent", "severe_respiratory_distress": "absent",
        "chest_pain_radiating": "absent", "diaphoresis": "absent",
        "pale_cold_sweaty": "absent",
    }
    q1 = next_question(criteria, inputs(findings=findings))
    assert q1.id == "cp_onset"
    q2 = next_question(criteria, inputs(findings=findings, answered_slots={"onset"}))
    assert q2.id == "cp_duration"


def test_asked_questions_never_repeat(criteria):
    seen = set()
    state_findings = {}
    answered = set()
    for _ in range(20):
        q = next_question(criteria, inputs(
            findings=state_findings, answered_slots=answered, asked=seen,
        ))
        if q is None:
            break
        assert q.id not in seen
        seen.add(q.id)
    assert q is None  # interview exhausts


def test_scale_resolved_by_severity_slot(criteria):
    findings = {
        "dyspnea": "absent", "severe_respiratory_distress": "absent",
        "chest_pain_radiating": "absent", "diaphoresis": "absent",
        "pale_cold_sweaty": "absent",
    }
    ivs = inputs(
        findings=findings,
        answered_slots={"onset", "duration", "character", "severity"},
    )
    q = next_question(criteria, ivs)
    assert q is not None and q.id == "cp_history"  # associated, not the scale


def test_generic_template_used_for_unknown_category(criteria):
    q = next_question(criteria, inputs(category="totally_new_complaint"))
    assert q.id == "uq_breathing"
    q2 = next_question(criteria, inputs(
        category="totally_new_complaint",
        findings={"dyspnea": "absent", "severe_respiratory_distress": "absent"},
    ))
    assert q2.id.startswith("gen_")


def test_complete_immediately_for_level_1_2(criteria):
    assert is_interview_complete(criteria, inputs(), provisional_level=1)
    assert is_interview_complete(criteria, inputs(), provisional_level=2)


def test_incomplete_while_red_flags_unresolved(criteria):
    assert not is_interview_complete(criteria, inputs(), provisional_level=4)


def test_budget_exhaustion_completes(criteria):
    assert is_interview_complete(
        criteria, inputs(questions_asked=8, budget=8), provisional_level=4,
    )


def test_min_slots_satisfied_completes(criteria):
    findings = {
        "dyspnea": "absent", "severe_respiratory_distress": "absent",
        "chest_pain_radiating": "absent", "diaphoresis": "absent",
        "pale_cold_sweaty": "absent",
    }
    ivs = inputs(findings=findings, answered_slots={"onset", "duration", "character"})
    # chest_pain min_slots_by_level[4] == 3
    assert is_interview_complete(criteria, ivs, provisional_level=4)


def test_bilingual_texts_on_every_question(criteria):
    templates = list(criteria.complaint_templates)
    all_questions = list(criteria.universal_questions)
    for t in templates:
        all_questions.extend(t.questions)
    for q in all_questions:
        assert q.text_en.strip(), q.id
        assert q.text_th.strip(), q.id
