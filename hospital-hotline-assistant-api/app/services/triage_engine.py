"""Compatibility facade for the refactored triage engine.

Also exposes ``run_triage`` -- the single async entry-point for the hybrid
RAG + Rule Engine pipeline.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.ai.triage_engine import LlmTriageEngine
from app.services.ai.triage_models import TriageDecision, TriageEngine

logger = logging.getLogger(__name__)

__all__ = [
    "LlmTriageEngine",
    "TriageDecision",
    "TriageEngine",
    "run_triage",
]


async def run_triage(
    patient_input: dict[str, Any],
    emergency_triggers: list[dict[str, Any]] | None = None,
    routing_rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Single entry-point for the hybrid triage pipeline."""
    try:
        from app.services.ai.triage_rag_agent import triage_patient
        result = await triage_patient(
            patient_input=patient_input,
            emergency_triggers=emergency_triggers,
            routing_rules=routing_rules,
        )
        payload = result.model_dump()
        payload["source"] = "rule_engine" if result.is_rule_based else "rag_llm"
        return payload
    except Exception:
        session_id = patient_input.get("session_id", "unknown")
        logger.exception("[session=%s] run_triage failed -- safe fallback.", session_id)
        return {
            "triage_level": "level_3",
            "severity": "general",
            "department_code": "general_opd",
            "key_reason": "System error -- safe fallback applied.",
            "symptoms_summary": None,
            "reply": (
                "Sorry, system error. Please contact the nurse directly."
            ),
            "is_rule_based": False,
            "requires_nurse_review": True,
            "source": "fallback",
        }
