from app.services.ai.tools import record_contact_preference


def test_contact_preference_records_requested_true():
    result = record_contact_preference(
        requested=True,
        confidence=0.9,
    )

    assert result["contact_preference_recorded"] is True
    assert result["requested"] is True
    assert result["confidence"] == 0.9


def test_contact_preference_records_phone_number():
    result = record_contact_preference(
        requested=True,
        phone_number="0812345678",
        confidence=0.95,
    )

    assert result["requested"] is True
    assert result["phone_number"] == "0812345678"


def test_contact_preference_records_requested_false():
    result = record_contact_preference(
        requested=False,
        confidence=0.85,
    )

    assert result["requested"] is False
    assert result["needs_followup"] is False


def test_contact_preference_records_unclear_followup():
    result = record_contact_preference(
        requested=None,
        confidence=0.3,
        needs_followup=True,
        followup_question="Would you like the hospital to contact you?",
    )

    assert result["requested"] is None
    assert result["needs_followup"] is True
    assert result["followup_question"] == "Would you like the hospital to contact you?"
