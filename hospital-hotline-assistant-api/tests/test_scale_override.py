from app.services.rule_engine import evaluate_scale_override


def test_cough_without_scale_or_red_flags_has_no_override():
    result = evaluate_scale_override(
        {
            "symptoms_summary": "Cough for two days",
            "red_flags": [],
        },
        "general",
    )

    assert result.severity is None


def test_breathing_difficulty_with_distress_score_9_is_emergency():
    result = evaluate_scale_override(
        {
            "distress_score": 9,
            "distress_type": "breathing_difficulty",
            "red_flags": ["breathing_difficulty"],
        },
        "general",
    )

    assert result.severity == "emergency"


def test_chest_pain_with_pain_score_8_is_emergency():
    result = evaluate_scale_override(
        {
            "pain_score": 8,
            "pain_location": "chest",
            "red_flags": [],
        },
        "urgent",
    )

    assert result.severity == "emergency"


def test_ankle_pain_score_9_without_red_flags_is_urgent_not_emergency():
    result = evaluate_scale_override(
        {
            "pain_score": 9,
            "pain_location": "ankle",
            "red_flags": [],
        },
        "general",
    )

    assert result.severity == "urgent"


def test_critical_red_flag_is_emergency_without_score():
    result = evaluate_scale_override(
        {
            "pain_score": None,
            "distress_score": None,
            "red_flags": ["blue_lips"],
        },
        "general",
    )

    assert result.severity == "emergency"


def test_existing_emergency_is_never_downgraded_or_replaced():
    result = evaluate_scale_override(
        {
            "pain_score": 9,
            "pain_location": "ankle",
            "red_flags": [],
        },
        "emergency",
    )

    assert result.severity is None
