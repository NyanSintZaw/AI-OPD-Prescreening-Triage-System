"""Question-policy tests: deterministic order, no repeats, completeness gate."""

import pytest

from app.services.screening.rules.question_policy import (
    InterviewInputs,
    confirm_question_for,
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
    ask_counts=None,
    gender="female",  # known, so uq_gender doesn't lead every ordering test
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
        ask_counts=ask_counts or {},
        gender=gender,
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
    # Measurements (temp priority 6, BP priority 7) precede OLDCARTS slots
    # (priority 10+).
    q0 = next_question(criteria, inputs(findings=findings))
    assert q0.id == "cp_temp"
    q1 = next_question(criteria, inputs(findings=findings, measured_vitals={"temp"}))
    assert q1.id == "cp_bp"
    q2 = next_question(criteria, inputs(
        findings=findings, measured_vitals={"temp", "sbp"},
    ))
    assert q2.id == "cp_onset"
    q3 = next_question(criteria, inputs(
        findings=findings, measured_vitals={"temp", "sbp"}, answered_slots={"onset"},
    ))
    assert q3.id == "cp_duration"


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
        measured_vitals={"sbp", "temp"},
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
        measured_vitals={"sbp", "temp", "weight"},
    )
    # chest_pain min_slots_by_level[4] == 3
    assert is_interview_complete(criteria, ivs, provisional_level=4)


def test_bp_always_asked_for_chest_pain(criteria):
    findings = {
        "dyspnea": "absent", "severe_respiratory_distress": "absent",
        "chest_pain_radiating": "absent", "diaphoresis": "absent",
        "pale_cold_sweaty": "absent",
    }
    q = next_question(criteria, inputs(findings=findings, measured_vitals={"temp"}))
    assert q is not None and q.id == "cp_bp" and q.vital == "sbp"


def test_bp_always_asked_for_ear_under_60(criteria):
    """Meeting 2026-07-17: vitals always recorded — BP is no longer age-gated."""
    findings = {
        "dyspnea": "absent", "severe_respiratory_distress": "absent",
        "facial_droop": "absent", "foreign_body_ent_24h": "absent",
    }
    seen = set()
    found = None
    for _ in range(20):
        q = next_question(criteria, inputs(
            category="ear", findings=findings, age_years=45.0, asked=seen,
            answered_slots={"onset", "duration", "severity"},
        ))
        if q is None:
            break
        if q.id == "ear_bp":
            found = q
            break
        seen.add(q.id)
    assert found is not None and found.vital == "sbp"


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


def test_bp_asked_when_age_unknown(criteria):
    findings = {
        "dyspnea": "absent", "severe_respiratory_distress": "absent",
        "facial_droop": "absent", "foreign_body_ent_24h": "absent",
    }
    seen = {"uq_age"}
    found = None
    for _ in range(20):
        q = next_question(criteria, inputs(
            category="ear", findings=findings, age_known=False, asked=seen,
            answered_slots={"onset", "duration", "severity"},
        ))
        if q is None:
            break
        if q.id == "ear_bp":
            found = q
            break
        seen.add(q.id)
    assert found is not None and found.vital == "sbp"


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
        measured_vitals={"sbp", "temp"},
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
    # Breathing difficulty confirmed → the booth measures SpO2 before any
    # template question (universal, gated on dyspnea) …
    q = next_question(criteria, inputs(category="dyspnea_cough", findings=findings))
    assert q is not None and q.id == "uq_spo2"
    # … and once measured, the distress scale follows as before.
    q = next_question(criteria, inputs(
        category="dyspnea_cough", findings=findings, measured_vitals={"spo2"},
    ))
    assert q is not None and q.id == "dc_distress_scale"


def test_spo2_never_requested_without_dyspnea(criteria):
    """The oximeter ask is gated: an unknown or absent dyspnea finding never
    triggers it, in any category."""
    for category in ("fever", "generic", "abdominal_pain"):
        seen: set[str] = set()
        for _ in range(25):
            q = next_question(criteria, inputs(
                category=category, findings={"dyspnea": "absent"}, asked=seen,
                measured_vitals={"sbp", "temp", "weight"},
            ))
            if q is None:
                break
            assert q.id != "uq_spo2", category
            seen.add(q.id)


def test_spo2_requested_for_any_category_once_dyspnea_present(criteria):
    q = next_question(criteria, inputs(
        category="fever",
        findings={"dyspnea": "present", "severe_respiratory_distress": "absent"},
    ))
    assert q is not None and q.id == "uq_spo2" and q.vital == "spo2"


def test_temp_measurement_asked_for_every_patient(criteria):
    """MFU manual scope: อุณหภูมิ ผู้ป่วยนอกทุกราย — temperature is a standard
    booth vital in every template, requested even when fever is denied
    (communicable-disease screening), and resolves once measured."""
    # Fever denied -> the temperature measurement is still requested.
    no_fever = {"fever": "absent"}
    seen = set()
    saw_temp = False
    for _ in range(20):
        q = next_question(criteria, inputs(
            category="fever", findings=no_fever, asked=seen,
            measured_vitals={"sbp", "weight"},
        ))
        if q is None:
            break
        if q.id == "fv_temp":
            saw_temp = True
            break
        seen.add(q.id)
    assert saw_temp

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


# ── Measurement re-ask: one retry when no usable value came back ──────────
#
# A measurement whose value never arrived — or arrived physiologically
# impossible and was rejected — gets exactly ONE more attempt, then is left
# missing so a patient typing nonsense can't loop the interview forever.


FEBRILE = {
    "fever": "present", "confusion": "absent", "dyspnea": "absent",
    "severe_respiratory_distress": "absent", "stiff_neck": "absent",
    "recent_chemotherapy": "absent", "rash_vesicles": "absent",
    "palm_sole_rash": "absent",
}


def test_measurement_reasked_once_when_no_value_arrived(criteria):
    """Asked once, still unmeasured → ask again."""
    asked_once = inputs(
        category="fever",
        findings=FEBRILE,
        asked=("fv_temp",),
        ask_counts={"fv_temp": 1},
    )
    q = next_question(criteria, asked_once)
    assert q is not None and q.id == "fv_temp"


def test_measurement_gives_up_after_two_asks(criteria):
    """Two asks with nothing usable → resolved (skipped), interview moves on."""
    asked_twice = inputs(
        category="fever",
        findings=FEBRILE,
        asked=("fv_temp",),
        ask_counts={"fv_temp": 2},
    )
    q = next_question(criteria, asked_twice)
    assert q is None or q.id != "fv_temp"


def test_measurement_resolves_immediately_on_a_good_value(criteria):
    """A plausible reading resolves it on the first ask — no pointless repeat."""
    answered = inputs(
        category="fever",
        findings=FEBRILE,
        asked=("fv_temp",),
        ask_counts={"fv_temp": 1},
        measured_vitals={"temp"},
    )
    q = next_question(criteria, answered)
    assert q is None or q.id != "fv_temp"


def test_measurement_reask_still_terminates_the_interview(criteria):
    """The re-ask must not deadlock the completeness gate."""
    spent = inputs(questions_asked=8, budget=8, ask_counts={"pd_weight_height": 1})
    assert not is_interview_complete(criteria, spent, provisional_level=4)
    assert next_question(criteria, spent).id == "pd_weight_height"

    exhausted = inputs(questions_asked=8, budget=8, ask_counts={"pd_weight_height": 2})
    assert is_interview_complete(criteria, exhausted, provisional_level=4)
    assert next_question(criteria, exhausted) is None


def test_measurement_holds_completeness_when_slots_fill_early(criteria):
    """A complaint sentence that fills the minimum slots on turn 1 must not
    dispose past the BP question (live E2E 2026-08-04: dizziness interview
    disposed without ever measuring BP — a hypertensive crisis would have
    walked through unmeasured)."""
    findings = {
        "dyspnea": "absent", "severe_respiratory_distress": "absent",
        "chest_pain_radiating": "absent", "diaphoresis": "absent",
        "pale_cold_sweaty": "absent",
    }
    ivs = inputs(
        findings=findings,
        answered_slots={"onset", "duration", "character"},
        measured_vitals={"temp", "weight"},   # wrap-up done; BP still missing
    )
    assert not is_interview_complete(criteria, ivs, provisional_level=4)
    q = next_question(criteria, ivs)
    assert q is not None and q.id == "cp_bp"

    # Once measured (or twice asked), the hold releases.
    measured = inputs(
        findings=findings,
        answered_slots={"onset", "duration", "character"},
        measured_vitals={"sbp", "temp", "weight"},
    )
    assert is_interview_complete(criteria, measured, provisional_level=4)
    twice_asked = inputs(
        findings=findings,
        answered_slots={"onset", "duration", "character"},
        measured_vitals={"temp", "weight"},
        asked=("cp_bp",),
        ask_counts={"cp_bp": 2},
    )
    assert is_interview_complete(criteria, twice_asked, provisional_level=4)


def test_volunteered_finding_does_not_close_a_compound_red_flag(criteria):
    """One half of a compound red flag is not an answer to the other half.

    Triage eval 2026-08-10 (ur_th_flank_fever): the patient said "burning
    urine + fever + flank pain", extraction set fever=present, and
    ``ur_fever_flank`` was then treated as resolved — so vomiting was never
    asked. Same shape as the dangerous case: ``meningitis_suspect`` needs
    fever AND stiff_neck, so a headache patient who volunteers a fever must
    still be asked about neck stiffness.
    """

    resolved_breathing = {"dyspnea": "absent", "severe_respiratory_distress": "absent"}
    headache = {
        **resolved_breathing,
        "facial_droop": "absent", "limb_weakness": "absent",
        "slurred_speech": "absent", "sudden_vision_loss": "absent",
        "balance_loss": "absent", "headache_sudden_severe": "absent",
        "fever": "present",          # volunteered, stiff_neck still unknown
    }
    q = next_question(criteria, inputs(category="headache", findings=headache))
    assert q is not None and q.id == "hd_stiff_neck"
    assert not is_interview_complete(
        criteria, inputs(category="headache", findings=headache), provisional_level=4
    )

    urinary = {**resolved_breathing, "fever": "present"}
    q = next_question(criteria, inputs(category="urinary", findings=urinary))
    assert q is not None and q.id == "ur_fever_flank"

    # Terminates: unanswered after two asks, the interview moves on.
    twice = inputs(
        category="urinary",
        findings=urinary,
        asked=("ur_fever_flank",),
        ask_counts={"ur_fever_flank": 2},
    )
    assert next_question(criteria, twice).id != "ur_fever_flank"


def test_confirm_question_never_borrowed_from_another_template(criteria):
    """Live defect: a fish bone in the THROAT (category nose_throat) got the
    ear template's confirm question — "is something stuck in your ear?" — so a
    truthful "no" erased a real level-2 ENT foreign body. Only the session's
    own template may supply the verbatim wording; otherwise the synthesized
    category-neutral confirm is used."""

    q = confirm_question_for(criteria, "foreign_body_ent_24h", "nose_throat")
    assert q.id != "ear_fb"
    assert q.finding_ids == ["foreign_body_ent_24h"]
    # Category-neutral wording: it names throat too, not the ear alone.
    assert "throat" in q.text_en.lower() and "คอ" in q.text_th

    # Preserved: the nurse-authored question IS used verbatim in its own template.
    own = confirm_question_for(criteria, "foreign_body_ent_24h", "ear")
    assert own.id == "ear_fb"
    assert own.text_th == "มีสิ่งแปลกปลอมเข้าไปติดในหูไหมคะ"


def test_red_flag_answered_yes_is_not_echoed(criteria):
    """uq_breathing covers dyspnea + severe_respiratory_distress. A patient who
    answers it with "yes, trouble breathing" has answered; the identical words
    must not be asked again — the severity is for the follow-on questions.
    A present finding that predates the ask (volunteered) still asks once."""
    volunteered = inputs(category="dyspnea_cough", findings={"dyspnea": "present"})
    answered = inputs(
        category="dyspnea_cough", findings={"dyspnea": "present"},
        asked=["uq_breathing"], ask_counts={"uq_breathing": 1},
    )
    assert next_question(criteria, volunteered).id == "uq_breathing"
    nxt = next_question(criteria, answered)
    assert nxt is None or nxt.id != "uq_breathing"
