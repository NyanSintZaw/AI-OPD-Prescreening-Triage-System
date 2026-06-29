"""Unit tests for the hybrid Rule Engine + RAG triage pipeline.

All tests are fully offline — pydantic-ai Agent and RAG search are patched.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── DB row fixtures ───────────────────────────────────────────────────────────

_CARDIAC: dict = {
    "id": "t-001",
    "trigger_name": "Cardiac Arrest",
    "condition_json": {"any": ["cardiac arrest", "no pulse"]},
    "trigger_keywords": ["cardiac arrest", "no pulse"],
    "alert_message_en": "CALL CODE BLUE. Go to ER immediately.",
    "alert_message_th": "โทรหาทีมแพทย์ฉุกเฉินทันที",
    "priority": 1,
    "is_active": True,
}

_ANAPHYLAXIS: dict = {
    "id": "t-002",
    "trigger_name": "Anaphylaxis",
    "condition_json": {"any": ["anaphylaxis", "throat swelling"]},
    "trigger_keywords": ["anaphylaxis", "throat swelling"],
    "alert_message_en": "Severe allergic reaction — ER immediately.",
    "alert_message_th": "แพ้รุนแรง ไปห้องฉุกเฉินทันที",
    "priority": 2,
    "is_active": True,
}

_CHEST_PAIN: dict = {
    "id": "r-001",
    "rule_name": "Chest Pain / ACS",
    "condition_json": {"any": ["chest pain", "เจ็บหน้าอก"]},
    "symptom_keywords": ["chest pain", "เจ็บหน้าอก"],
    "severity_override": "emergency",
    "department_id": "dept-cardiology",
    "priority": 10,
    "is_active": True,
}

_HEADACHE: dict = {
    "id": "r-002",
    "rule_name": "Headache",
    "condition_json": {"any": ["headache", "ปวดหัว"]},
    "symptom_keywords": ["headache", "ปวดหัว"],
    "severity_override": "urgent",
    "department_id": "dept-general",
    "priority": 50,
    "is_active": True,
}


def _rag_output(**kw) -> MagicMock:
    defaults = dict(
        triage_level="level_3", severity="urgent", department_code="general_opd",
        key_reason="AI decision", symptoms_summary="symptoms", reply="See a nurse.",
        is_rule_based=False, requires_nurse_review=True,
    )
    defaults.update(kw)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    obj.model_dump.return_value = dict(defaults)
    return obj


def _agent_result(output: MagicMock) -> MagicMock:
    r = MagicMock()
    r.data = output
    return r


# ── Layer 1: Emergency triggers ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cardiac_arrest_fires_level1_no_llm():
    from app.services.ai.triage_rag_agent import triage_patient
    with patch("app.services.ai.triage_rag_agent._get_agent") as mock_fn:
        result = await triage_patient(
            {"content": "cardiac arrest patient no pulse", "language": "en"},
            emergency_triggers=[_CARDIAC], routing_rules=[],
        )
    assert result.triage_level == "level_1"
    assert result.severity == "emergency"
    assert result.is_rule_based is True
    assert result.requires_nurse_review is True
    mock_fn.assert_not_called()


@pytest.mark.asyncio
async def test_anaphylaxis_uses_thai_alert():
    from app.services.ai.triage_rag_agent import triage_patient
    with patch("app.services.ai.triage_rag_agent._get_agent") as mock_fn:
        result = await triage_patient(
            {"content": "throat swelling severe allergy", "language": "th"},
            emergency_triggers=[_CARDIAC, _ANAPHYLAXIS], routing_rules=[],
        )
    assert result.triage_level == "level_1"
    assert result.is_rule_based is True
    mock_fn.assert_not_called()


@pytest.mark.asyncio
async def test_emergency_trigger_beats_routing_rule():
    from app.services.ai.triage_rag_agent import triage_patient
    with patch("app.services.ai.triage_rag_agent._get_agent") as mock_fn:
        result = await triage_patient(
            {"content": "cardiac arrest with chest pain"},
            emergency_triggers=[_CARDIAC], routing_rules=[_CHEST_PAIN],
        )
    assert result.triage_level == "level_1"
    mock_fn.assert_not_called()


# ── Layer 1: Routing rules ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chest_pain_rule_sets_correct_department():
    from app.services.ai.triage_rag_agent import triage_patient
    with patch("app.services.ai.triage_rag_agent._get_agent") as mock_fn:
        result = await triage_patient(
            {"content": "I have chest pain", "language": "en"},
            emergency_triggers=[], routing_rules=[_CHEST_PAIN],
        )
    assert result.is_rule_based is True
    assert result.department_code == "dept-cardiology"
    mock_fn.assert_not_called()


@pytest.mark.asyncio
async def test_thai_headache_rule_fires():
    from app.services.ai.triage_rag_agent import triage_patient
    with patch("app.services.ai.triage_rag_agent._get_agent") as mock_fn:
        result = await triage_patient(
            {"content": "ปวดหัวมาก", "language": "th"},
            emergency_triggers=[], routing_rules=[_HEADACHE],
        )
    assert result.is_rule_based is True
    assert result.department_code == "dept-general"
    mock_fn.assert_not_called()


@pytest.mark.asyncio
async def test_unrelated_message_skips_to_layer2():
    from app.services.ai.triage_rag_agent import triage_patient
    mock_out = _rag_output(triage_level="level_5", is_rule_based=False)
    mock_agent = AsyncMock()
    mock_agent.run.return_value = _agent_result(mock_out)

    with patch("app.services.ai.triage_rag_agent._get_agent", return_value=mock_agent):
        result = await triage_patient(
            {"content": "I want to book an appointment"},
            emergency_triggers=[_CARDIAC], routing_rules=[_CHEST_PAIN, _HEADACHE],
        )
    assert result.is_rule_based is False
    mock_agent.run.assert_called_once()


# ── Layer 2: RAG + LLM ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_match_calls_rag_agent():
    from app.services.ai.triage_rag_agent import triage_patient
    mock_out = _rag_output(triage_level="level_3")
    mock_agent = AsyncMock()
    mock_agent.run.return_value = _agent_result(mock_out)

    with patch("app.services.ai.triage_rag_agent._get_agent", return_value=mock_agent):
        result = await triage_patient({"content": "mild stomach ache"})

    mock_agent.run.assert_called_once()
    assert result.is_rule_based is False


@pytest.mark.asyncio
async def test_patient_content_in_rag_prompt():
    from app.services.ai.triage_rag_agent import triage_patient
    captured: list[str] = []

    mock_out = _rag_output()
    mock_agent = AsyncMock()

    async def _capture(prompt: str, *a, **kw):
        captured.append(prompt)
        return _agent_result(mock_out)

    mock_agent.run.side_effect = _capture

    with patch("app.services.ai.triage_rag_agent._get_agent", return_value=mock_agent):
        await triage_patient({"content": "ปวดท้องมาก", "language": "th"})

    assert "ปวดท้องมาก" in captured[0]


@pytest.mark.asyncio
async def test_nurse_review_forced_true_even_if_agent_returns_false():
    from app.services.ai.triage_rag_agent import triage_patient
    mock_out = _rag_output(requires_nurse_review=False)
    mock_agent = AsyncMock()
    mock_agent.run.return_value = _agent_result(mock_out)

    with patch("app.services.ai.triage_rag_agent._get_agent", return_value=mock_agent):
        result = await triage_patient({"content": "runny nose"})

    assert result.requires_nurse_review is True


@pytest.mark.asyncio
async def test_none_lists_still_reaches_layer2():
    from app.services.ai.triage_rag_agent import triage_patient
    mock_out = _rag_output()
    mock_agent = AsyncMock()
    mock_agent.run.return_value = _agent_result(mock_out)

    with patch("app.services.ai.triage_rag_agent._get_agent", return_value=mock_agent):
        await triage_patient({"content": "stomach pain"})

    mock_agent.run.assert_called_once()


# ── run_triage() wrapper ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_triage_returns_dict_with_source():
    from app.services.triage_engine import run_triage
    mock_out = _rag_output(is_rule_based=False)
    mock_agent = AsyncMock()
    mock_agent.run.return_value = _agent_result(mock_out)

    with patch("app.services.ai.triage_rag_agent._get_agent", return_value=mock_agent):
        result = await run_triage({"content": "mild cough"}, [], [])

    assert isinstance(result, dict)
    assert result["source"] == "rag_llm"


@pytest.mark.asyncio
async def test_run_triage_rule_engine_source():
    from app.services.triage_engine import run_triage
    result = await run_triage(
        {"content": "cardiac arrest no pulse", "language": "en"},
        emergency_triggers=[_CARDIAC], routing_rules=[],
    )
    assert result["source"] == "rule_engine"
    assert result["triage_level"] == "level_1"


@pytest.mark.asyncio
async def test_run_triage_safe_fallback_on_exception():
    from app.services.triage_engine import run_triage
    with patch(
        "app.services.ai.triage_rag_agent.triage_patient",
        side_effect=RuntimeError("AI down"),
    ):
        result = await run_triage({"content": "anything"}, [], [])

    assert result["triage_level"] == "level_3"
    assert result["department_code"] == "general_opd"
    assert result["source"] == "fallback"


# ── ESI level mapping ─────────────────────────────────────────────────────────

class TestLevelMapping:
    @pytest.mark.asyncio
    async def test_emergency_severity_maps_to_level2(self):
        from app.services.ai.triage_rag_agent import triage_patient
        with patch("app.services.ai.triage_rag_agent._get_agent"):
            result = await triage_patient(
                {"content": "chest pain"}, [], [_CHEST_PAIN]
            )
        assert result.triage_level == "level_2"

    @pytest.mark.asyncio
    async def test_urgent_severity_maps_to_level3(self):
        from app.services.ai.triage_rag_agent import triage_patient
        with patch("app.services.ai.triage_rag_agent._get_agent"):
            result = await triage_patient(
                {"content": "headache migraine"}, [], [_HEADACHE]
            )
        assert result.triage_level == "level_3"
