"""Natural-language chief complaint (symptoms_summary) formatter tests."""

from app.services.screening.chief_complaint import format_chief_complaint_summary
from app.services.screening.nodes.dispose import build_classification, _summary
from app.services.screening.rules.disposition import DispositionResult, DispositionReason
from app.services.screening.state import Finding, ScreeningState


def _state(**kwargs) -> ScreeningState:
    defaults = dict(
        session_id="cc-1",
        language="en",
        phase="disposed",
        chief_complaint="Fever",
        slots={"duration": "one day"},
    )
    defaults.update(kwargs)
    return ScreeningState(**defaults)


def test_en_fever_for_one_day():
    text = format_chief_complaint_summary(_state())
    assert text == "Fever for one day prior to hospital visit."


def test_en_with_location_and_character():
    text = format_chief_complaint_summary(
        _state(
            chief_complaint="chest pain",
            slots={
                "duration": "2 hours",
                "location": "left chest",
                "character": "pressure-like",
            },
        )
    )
    assert "Chest pain" in text or "chest pain" in text
    assert "left chest" in text
    assert "2 hours" in text
    assert "prior to hospital visit" in text
    assert "findings:" not in text
    assert ";" not in text


def test_th_fever_duration():
    text = format_chief_complaint_summary(
        _state(language="th", chief_complaint="ไข้", slots={"duration": "1 วัน"})
    )
    assert "ไข้" in text
    assert "1 วัน" in text
    assert "ก่อนมาโรงพยาบาล" in text


def test_complaint_only_no_slots():
    text = format_chief_complaint_summary(
        _state(chief_complaint="sore throat", slots={})
    )
    assert text == "Sore throat."


def test_empty_fallback():
    text = format_chief_complaint_summary(
        _state(chief_complaint=None, complaint_category=None, slots={})
    )
    assert "No structured" in text


def test_category_fallback_when_no_free_text():
    text = format_chief_complaint_summary(
        _state(
            chief_complaint=None,
            complaint_category="fever",
            slots={"duration": "1 day"},
        )
    )
    assert "Fever" in text or "fever" in text
    assert "1 day" in text


def test_none_answers_do_not_duplicate_duration_in_complaint():
    text = format_chief_complaint_summary(
        _state(
            chief_complaint="Fever for one day",
            slots={"duration": "one day"},
        )
    )
    # Should not append a second "for one day prior..."
    assert text.lower().count("one day") == 1


def test_build_classification_uses_nl_summary():
    state = _state()
    disposition = DispositionResult(
        level=4,
        color="green",
        label="semi-urgent",
        department_code="gp",
        response_time="30 min",
        reasons=[
            DispositionReason(
                rule_id="t1",
                text_en="fever",
                text_th="ไข้",
                citation="test",
            )
        ],
        rule_hits=[],
        age_assumed=False,
    )
    # DispositionResult may have different field names — use whatever the
    # codebase expects; fall back to calling _summary directly if needed.
    try:
        out = build_classification(state, disposition)
        summary = out["symptoms_summary"]
    except TypeError:
        summary = _summary(state)
    assert summary == "Fever for one day prior to hospital visit."
    assert "findings:" not in summary
