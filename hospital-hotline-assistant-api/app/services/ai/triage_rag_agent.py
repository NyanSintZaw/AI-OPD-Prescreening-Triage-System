"""Hybrid triage agent: Rule Engine (Layer 1) + RAG-augmented LLM (Layer 2).

.. deprecated::
    This pydantic-ai stack (Stack B, ``POST /triage/rag``) is superseded by
    the deterministic screening engine v2 in ``app/services/screening/``
    (``TRIAGE_ENGINE=langgraph``), which replaces keyword matching over raw
    text with structured findings evaluated against versioned, nurse-approved
    criteria. The endpoint is kept for comparison/demo only — do not build
    new features on it.

Layer 1 — Hard rules (no LLM):
    Uses existing *rule_engine.py* to match emergency triggers and routing
    rules.  If a match is found the decision is returned immediately with
    ``is_rule_based=True`` and ``confidence=1.0``.

Layer 2 — RAG + LLM (pydantic-ai):
    A pydantic-ai Agent searches the hospital triage manual via the
    ``triage_manual_search`` tool and produces a structured ``RagTriageOutput``.
    ``requires_nurse_review`` is always True on every output.

Public entry-point::

    from app.services.ai.triage_rag_agent import triage_patient

    result = await triage_patient(
        patient_input={"content": "...", "language": "th"},
        emergency_triggers=[...],
        routing_rules=[...],
    )
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from app.services.ai.rag_query import search_triage_manual
from app.services.rule_engine import evaluate_emergency_triggers, evaluate_routing_rules

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------

class RagTriageOutput(BaseModel):
    """Structured triage decision produced by the hybrid agent."""

    triage_level: Literal["level_1", "level_2", "level_3", "level_4", "level_5"] = Field(
        description=(
            "ESI triage level. level_1=immediate life-threatening, "
            "level_2=emergency, level_3=urgent, level_4=less-urgent, level_5=non-urgent."
        )
    )
    severity: Literal["emergency", "urgent", "general", "unknown"] = Field(
        description="Aggregated severity bucket corresponding to triage_level."
    )
    department_code: str | None = Field(
        default=None,
        description="Recommended OPD department code.",
    )
    key_reason: str = Field(
        description="Short Thai/English explanation of the triage decision."
    )
    symptoms_summary: str | None = Field(
        default=None,
        description="One-sentence summary of the patient's reported symptoms.",
    )
    reply: str = Field(
        description=(
            "Patient-facing response in the same language the patient used. "
            "Include the recommended action."
        )
    )
    is_rule_based: bool = Field(default=False)
    requires_nurse_review: bool = Field(default=True)


# ---------------------------------------------------------------------------
# pydantic-ai Agent
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a triage assistant at Mae Fah Luang University Medical Center Hospital
(โรงพยาบาลศูนย์การแพทย์มหาวิทยาลัยแม่ฟ้าหลวง).
You MUST follow the hospital's official triage manual strictly.
Always use the triage_manual_search tool before making any routing decision.
When vital signs indicate Level 1 emergency, always output triage_level="level_1" immediately.
When in doubt, ALWAYS escalate to a higher urgency level — never downgrade.
You recommend only — nurses always do the final review.
Never answer questions outside triage scope.
Respond in Thai if the patient input is Thai.
"""

_agent: "Agent[None, RagTriageOutput] | None" = None


def _make_agent(model_name: str) -> "Agent[None, RagTriageOutput]":
    agent: Agent[None, RagTriageOutput] = Agent(
        model=f"google-vertex:{model_name}",
        result_type=RagTriageOutput,
        system_prompt=_SYSTEM_PROMPT,
    )

    @agent.tool
    async def triage_manual_search(ctx: RunContext[None], query: str) -> str:
        """Search MFU hospital official triage guidelines.

        Use for department routing, symptom criteria, urgency classification.
        Input: patient symptoms in Thai or English.
        """
        return await search_triage_manual(query)

    return agent


def _get_agent() -> "Agent[None, RagTriageOutput]":
    global _agent
    if _agent is None:
        from app.config import settings
        _agent = _make_agent(settings.google_model_name)
    return _agent


# ---------------------------------------------------------------------------
# Public async entry-point
# ---------------------------------------------------------------------------

async def triage_patient(
    patient_input: dict[str, Any],
    emergency_triggers: list[dict[str, Any]] | None = None,
    routing_rules: list[dict[str, Any]] | None = None,
) -> RagTriageOutput:
    """Run the hybrid triage pipeline for a single patient turn.

    Layer 1 evaluates hard rules; Layer 2 uses RAG + LLM when no rule fires.

    Args:
        patient_input: Dict with ``content`` (str), optional ``language`` and
                       ``session_id``.
        emergency_triggers: Rows from the ``emergency_triggers`` DB table.
        routing_rules:      Rows from the ``routing_rules`` DB table.

    Returns:
        ``RagTriageOutput`` with ``requires_nurse_review=True`` always.
    """
    content: str = patient_input.get("content", "")
    language: str = patient_input.get("language", "th")
    session_id: str = patient_input.get("session_id", "unknown")

    # ── Layer 1: Emergency triggers ──────────────────────────────────────────
    if emergency_triggers:
        em_matches = evaluate_emergency_triggers(content, emergency_triggers, language=language)
        if em_matches:
            best = em_matches[0]
            logger.info("[session=%s] Emergency trigger: %s", session_id, best.name)
            return RagTriageOutput(
                triage_level="level_1",
                severity="emergency",
                department_code="emergency",
                key_reason=f"Emergency trigger: {best.name}",
                symptoms_summary=content[:200],
                reply=best.alert_message or "กรุณาไปห้องฉุกเฉินทันที (Please go to the ER immediately.)",
                is_rule_based=True,
                requires_nurse_review=True,
            )

    # ── Layer 1: Routing rules ───────────────────────────────────────────────
    if routing_rules:
        rt_matches = evaluate_routing_rules(content, routing_rules)
        if rt_matches:
            best = rt_matches[0]
            severity = best.severity_override or "general"
            level_map = {"emergency": "level_2", "urgent": "level_3", "general": "level_4", "unknown": "level_4"}
            triage_level = level_map.get(str(severity), "level_4")
            logger.info("[session=%s] Routing rule: %s → dept=%s", session_id, best.name, best.department_id)
            return RagTriageOutput(
                triage_level=triage_level,  # type: ignore[arg-type]
                severity=severity if severity in ("emergency", "urgent", "general", "unknown") else "general",  # type: ignore[arg-type]
                department_code=best.department_id,
                key_reason=f"Routing rule: {best.name}",
                symptoms_summary=content[:200],
                reply=f"ท่านควรไปพบแพทย์ที่แผนก {best.name} (Please proceed to the {best.name} department.)",
                is_rule_based=True,
                requires_nurse_review=True,
            )

    # ── Layer 2: RAG + LLM ───────────────────────────────────────────────────
    logger.info("[session=%s] No rule matched — delegating to RAG+LLM.", session_id)
    user_prompt = f"ภาษา/Language: {language}\nอาการผู้ป่วย/Patient symptoms:\n{content}"
    agent = _get_agent()
    run_result = await agent.run(user_prompt)
    output: RagTriageOutput = run_result.data
    output.requires_nurse_review = True
    output.is_rule_based = False
    return output
