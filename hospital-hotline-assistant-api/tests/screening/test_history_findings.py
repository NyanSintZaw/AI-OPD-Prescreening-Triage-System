"""Tests for HN history → risk-factor findings mapping."""

from app.services.screening.history_findings import apply_history_findings
from app.services.screening.state import ScreeningState


def _state() -> ScreeningState:
    return ScreeningState(
        session_id="hist-1",
        language="en",
        phase="history",
        turn_count=1,
    )


def test_diabetes_chronic_conditions_sets_finding():
    state = _state()
    apply_history_findings(state, {"chronic_conditions": "diabetes type 2"})
    assert state.findings["diabetes_history"].state == "present"


def test_english_lay_phrasings_set_findings():
    # Patients write "high blood pressure", not "hypertension" — both the
    # clinical and the lay phrasing must stamp the risk finding.
    state = _state()
    apply_history_findings(
        state,
        {"chronic_conditions": "High blood pressure since 2023; high blood sugar"},
    )
    assert state.findings["hypertension_history"].state == "present"
    assert state.findings["diabetes_history"].state == "present"


def test_word_order_and_typo_phrasings(  # live E2E finding (July 22)
):
    # "my blood pressure has been high" — HTN stated in a different word
    # order than "high blood pressure"; also the common 'hypertention' typo.
    for text in (
        "my doctor said my blood pressure has been high since last year",
        "hypertention",
        "น้ำตาลในเลือดสูง",  # lay Thai for diabetes → diabetes branch below
    ):
        state = _state()
        apply_history_findings(state, {"chronic_conditions": text})
        stamped = {k for k, f in state.findings.items() if f.state == "present"}
        assert stamped, text
    state = _state()
    apply_history_findings(
        state,
        {"chronic_conditions": "my blood pressure has been high lately"},
    )
    assert state.findings["hypertension_history"].state == "present"


def test_negated_habits_and_allergies_do_not_fire():
    # live E2E finding (July 22): "never smoked / never drinks" must not
    # stamp risk factors; per-substance so a mixed answer still works.
    state = _state()
    apply_history_findings(
        state,
        {
            "smoking_alcohol": "ไม่เคยสูบ ไม่ดื่ม",
            "allergies": "no allergies that I know of",
        },
    )
    assert "smoking" not in state.findings
    assert "alcohol_use" not in state.findings
    assert "allergy_history" not in state.findings

    mixed = _state()
    apply_history_findings(mixed, {"smoking_alcohol": "ไม่สูบ แต่ดื่มเหล้าหนักทุกวัน"})
    assert "smoking" not in mixed.findings
    assert mixed.findings["alcohol_use"].state == "present"

    ex_smoker = _state()
    apply_history_findings(ex_smoker, {"smoking_alcohol": "quit smoking 10 years ago"})
    # Former smoker remains a risk factor; verbatim detail rides the value.
    assert ex_smoker.findings["smoking"].state == "present"


def test_thai_hypertension_and_smoking_alcohol():
    state = _state()
    apply_history_findings(
        state,
        {
            "chronic_conditions": "ความดันโลหิตสูง",
            "smoking_alcohol": "สูบบุหรี่ทุกวัน ดื่มเหล้านาน ๆ ครั้ง",
        },
    )
    assert state.findings["hypertension_history"].state == "present"
    assert state.findings["smoking"].state == "present"
    assert state.findings["alcohol_use"].state == "present"


def test_allergies_surgeries_family():
    state = _state()
    apply_history_findings(
        state,
        {
            "allergies": "penicillin",
            "past_surgeries": "appendectomy 2019",
            "family_history": "father has diabetes",
        },
    )
    assert state.findings["allergy_history"].state == "present"
    assert state.findings["past_surgery_history"].state == "present"
    assert state.findings["family_history_chronic"].state == "present"
    # Family text must not stamp the patient's own diabetes finding.
    assert "diabetes_history" not in state.findings


def test_none_answers_do_not_fire():
    state = _state()
    apply_history_findings(
        state,
        {
            "allergies": "none",
            "chronic_conditions": "ไม่มี",
            "smoking_alcohol": "ไม่สูบ",
            "past_surgeries": "-",
            "family_history": "n/a",
        },
    )
    assert state.findings == {}


def test_engine_turn_context_applies_history():
    from app.services.screening.engine import ScreeningTriageEngine

    state = _state()
    ScreeningTriageEngine._apply_turn_context(
        state,
        {"patient_history": {"chronic_conditions": "diabetes"}},
    )
    assert state.findings["diabetes_history"].state == "present"
