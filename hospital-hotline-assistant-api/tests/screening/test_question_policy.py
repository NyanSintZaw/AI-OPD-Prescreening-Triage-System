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
    age_years=35.0,
    measured_vitals=(),
    questions_asked=0,
    budget=8,
):
    return InterviewInputs(
        complaint_category=category,
        findings=findings or {},
        answered_slots=frozenset(answered_slots),
        asked_question_ids=frozenset(asked),
        age_known=age_known,
        age_years=None if not age_known else age_years,
        measured_vitals=frozenset(measured_vitals),
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
    # BP measurement (priority 7) precedes OLDCARTS slots (priority 10+).
    q0 = next_question(criteria, inputs(findings=findings))
    assert q0.id == "cp_bp"
    q1 = next_question(criteria, inputs(findings=findings, measured_vitals={"sbp"}))
    assert q1.id == "cp_onset"
    q2 = next_question(criteria, inputs(
        findings=findings, measured_vitals={"sbp"}, answered_slots={"onset"},
    ))
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
        measured_vitals={"sbp"},
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
    # Budget exhaustion ends the interview once wrap-up measurements are done…
    assert is_interview_complete(
        criteria,
        inputs(questions_asked=8, budget=8, measured_vitals={"weight", "height"}),
        provisional_level=4,
    )
    # …but still holds for the (at most once) weight/height request, which
    # next_question then serves exclusively.
    spent = inputs(questions_asked=8, budget=8)
    assert not is_interview_complete(criteria, spent, provisional_level=4)
    q = next_question(criteria, spent)
    assert q is not None and q.id == "pd_weight_height"
    # once asked, it's resolved even without a reading — no infinite hold
    asked = inputs(questions_asked=8, budget=8, asked=("pd_weight_height",))
    assert is_interview_complete(criteria, asked, provisional_level=4)
    assert next_question(criteria, asked) is None


def test_min_slots_satisfied_completes(criteria):
    findings = {
        "dyspnea": "absent", "severe_respiratory_distress": "absent",
        "chest_pain_radiating": "absent", "diaphoresis": "absent",
        "pale_cold_sweaty": "absent",
    }
    # Weight/height pre-disposition must be measured before min-slots can complete.
    ivs = inputs(
        findings=findings,
        answered_slots={"onset", "duration", "character"},
        measured_vitals={"sbp", "weight"},
    )
    # chest_pain min_slots_by_level[4] == 3
    assert is_interview_complete(criteria, ivs, provisional_level=4)


def test_bp_always_asked_for_chest_pain(criteria):
    findings = {
        "dyspnea": "absent", "severe_respiratory_distress": "absent",
        "chest_pain_radiating": "absent", "diaphoresis": "absent",
        "pale_cold_sweaty": "absent",
    }
    q = next_question(criteria, inputs(findings=findings))
    assert q is not None and q.id == "cp_bp" and q.vital == "sbp"


def test_bp_skipped_for_ear_under_60(criteria):
    findings = {
        "dyspnea": "absent", "severe_respiratory_distress": "absent",
        "facial_droop": "absent", "foreign_body_ent_24h": "absent",
    }
    q = next_question(criteria, inputs(
        category="ear", findings=findings, age_years=45.0,
    ))
    assert q is None or q.id != "ear_bp"


def test_bp_asked_for_ear_age_60_plus(criteria):
    findings = {
        "dyspnea": "absent", "severe_respiratory_distress": "absent",
        "facial_droop": "absent", "foreign_body_ent_24h": "absent",
    }
    seen = set()
    found = None
    for _ in range(20):
        q = next_question(criteria, inputs(
            category="ear", findings=findings, age_years=65.0, asked=seen,
            answered_slots={"onset", "duration", "severity"},
        ))
        if q is None:
            break
        if q.id == "ear_bp":
            found = q
            break
        seen.add(q.id)
    assert found is not None and found.vital == "sbp"


def test_bp_skipped_when_age_unknown_on_age_gated(criteria):
    findings = {
        "dyspnea": "absent", "severe_respiratory_distress": "absent",
        "facial_droop": "absent", "foreign_body_ent_24h": "absent",
    }
    q = next_question(criteria, inputs(
        category="ear", findings=findings, age_known=False,
    ))
    # age unknown -> ear_bp resolved/skipped; age question comes first instead
    assert q is not None and q.id == "uq_age"


def test_pre_disposition_holds_completeness(criteria):
    findings = {
        "dyspnea": "absent", "severe_respiratory_distress": "absent",
        "chest_pain_radiating": "absent", "diaphoresis": "absent",
        "pale_cold_sweaty": "absent",
    }
    ivs = inputs(
        findings=findings,
        answered_slots={"onset", "duration", "character"},
        measured_vitals={"sbp"},  # weight still missing
    )
    assert not is_interview_complete(criteria, ivs, provisional_level=4)


def test_pre_disposition_asked_after_template(criteria):
    findings = {
        "dyspnea": "absent", "severe_respiratory_distress": "absent",
        "chest_pain_radiating": "absent", "diaphoresis": "absent",
        "pale_cold_sweaty": "absent",
        "heart_disease_history": "absent", "hypertension_history": "absent",
        "diabetes_history": "absent", "smoking": "absent",
    }
    q = next_question(criteria, inputs(
        findings=findings,
        answered_slots={"onset", "duration", "character", "severity"},
        measured_vitals={"sbp"},
        asked={"cp_history"},
    ))
    assert q is not None and q.id == "pd_weight_height" and q.vital == "weight"


def test_slot_questions_have_authored_options(criteria):
    cp = next(t for t in criteria.complaint_templates if t.category == "chest_pain")
    onset = next(q for q in cp.questions if q.id == "cp_onset")
    assert onset.options
    assert all(o.text_en and o.text_th for o in onset.options)


def test_intake_asked_first_when_no_complaint(criteria):
    # No chief complaint yet (vague / STT garble) -> ask what brought them in,
    # before any age or red-flag question.
    q = next_question(criteria, inputs(category=None, age_known=False))
    assert q is not None and q.id == "uq_intake"


def test_intake_resolved_once_complaint_known(criteria):
    # With a complaint category set, intake is resolved; age/red-flags proceed.
    q = next_question(criteria, inputs(category="chest_pain", age_known=False))
    assert q.id == "uq_age"


def test_breathing_scale_skipped_when_dyspnea_absent(criteria):
    findings = {"dyspnea": "absent", "severe_respiratory_distress": "absent"}
    ivs = inputs(
        category="dyspnea_cough",
        findings=findings,
        answered_slots={"onset", "duration"},
    )
    # dc_distress_scale must never surface without breathing trouble present.
    seen = set()
    cur = ivs
    for _ in range(20):
        q = next_question(criteria, cur)
        if q is None:
            break
        assert q.id != "dc_distress_scale"
        seen.add(q.id)
        cur = inputs(
            category="dyspnea_cough", findings=findings,
            answered_slots=cur.answered_slots, asked=seen,
            measured_vitals=cur.measured_vitals,
        )


def test_breathing_scale_fires_when_dyspnea_present(criteria):
    findings = {
        "dyspnea": "present", "severe_respiratory_distress": "absent",
        "blue_lips": "absent", "hemoptysis": "absent", "chest_pain": "absent",
        "fever": "absent", "high_fever": "absent",
    }
    q = next_question(criteria, inputs(category="dyspnea_cough", findings=findings))
    assert q is not None and q.id == "dc_distress_scale"


def test_temp_measurement_fires_only_when_fever_present(criteria):
    # No fever -> temperature never requested.
    no_fever = {"fever": "absent"}
    seen = set()
    for _ in range(20):
        q = next_question(criteria, inputs(
            category="fever", findings=no_fever, asked=seen,
            measured_vitals={"sbp", "weight"},
        ))
        if q is None:
            break
        assert q.id != "fv_temp"
        seen.add(q.id)

    # Fever present + temp not yet measured -> the measurement is requested.
    febrile = {"fever": "present", "confusion": "absent", "dyspnea": "absent",
               "severe_respiratory_distress": "absent",
               "stiff_neck": "absent", "recent_chemotherapy": "absent",
               "rash_vesicles": "absent", "palm_sole_rash": "absent"}
    q = next_question(criteria, inputs(category="fever", findings=febrile))
    assert q is not None and q.id == "fv_temp" and q.vital == "temp"

    # Once temp is measured, the measurement resolves and drops out.
    q2 = next_question(criteria, inputs(
        category="fever", findings=febrile, measured_vitals={"temp"},
    ))
    assert q2 is None or q2.id != "fv_temp"


def test_bilingual_texts_on_every_question(criteria):
    templates = list(criteria.complaint_templates)
    all_questions = list(criteria.universal_questions)
    all_questions.extend(criteria.pre_disposition_questions)
    for t in templates:
        all_questions.extend(t.questions)
    for q in all_questions:
        assert q.text_en.strip(), q.id
        assert q.text_th.strip(), q.id
