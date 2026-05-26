from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

import asyncpg

from app.config import settings
from app.services.adk_agent import HotlineADKRunner
from app.services.notification_service import (
    BaseNotificationService,
    EmergencyAlert,
    MockNotificationService,
)
from app.services.rule_engine import evaluate_emergency_triggers, evaluate_routing_rules


# Five-level (ADK) → legacy 4-bucket severity. Lives at module scope so
# it's allocated once and easy to find from tests / dashboards.
_LEVEL_TO_SEVERITY: dict[int, str] = {
    1: "emergency",
    2: "emergency",
    3: "urgent",
    4: "general",
    5: "general",
}


@dataclass
class TriageResult:
    reply: str
    severity_level: str
    severity_explanation: str | None
    severity_confidence: float | None
    department_id: str | None
    department_reason: str | None
    department_confidence: float | None
    emergency_trigger_id: str | None
    emergency_alert_message: str | None
    detected_symptoms: list[str]
    follow_up_question: str | None
    follow_up_reason: str | None
    model_name: str | None
    latency_ms: int
    alert_sent: bool


class TriageService:
    def __init__(self, notifier: BaseNotificationService | None = None) -> None:
        # ADK drives the AI brain (Orchestrator → TriageAgent / EmergencyAgent).
        # The runner owns the InMemorySessionService that holds per-call
        # conversation state, so the legacy "fetch last 20 messages from
        # Postgres" history step is gone -- ADK handles turn history.
        self.adk_runner = HotlineADKRunner()
        # Default to the mock notifier so the demo + tests work without
        # any external transport. Callers can inject a production sink
        # (LINE / FCM / SMS) once those services land.
        self.notifier: BaseNotificationService = notifier or MockNotificationService()

    async def process_chat(
        self,
        *,
        connection: asyncpg.Connection,
        session_id: str,
        language: str,
        input_mode: str,
        content: str,
    ) -> tuple[TriageResult, dict[str, Any]]:
        start = perf_counter()

        session_row = await connection.fetchrow(
            "SELECT id, language, metadata FROM sessions WHERE id = $1",
            session_id,
        )
        if not session_row:
            raise ValueError("Session not found")

        # Carry triage state across turns. ADK calls ``classify_triage_level``
        # once (turn the symptoms come in) and ``collect_emergency_contact``
        # once (turn the last contact field is provided); intermediate turns
        # emit no tool output. Without this, severity/department/contact all
        # reset to "unknown" mid-conversation and the EmergencyAgent's
        # multi-turn name → phone → address handoff never reaches a state
        # where the notifier can fire with full info.
        prior_metadata: dict[str, Any] = dict(session_row["metadata"] or {})
        prior_classification: dict[str, Any] = (
            prior_metadata.get("triage_classification") or {}
        )
        prior_contact: dict[str, Any] = prior_metadata.get("emergency_contact") or {}

        msg_user = await connection.fetchrow(
            """
            INSERT INTO messages (session_id, role, input_mode, content, metadata)
            VALUES ($1, 'user', $2, $3, '{}'::jsonb)
            RETURNING *
            """,
            session_id,
            input_mode,
            content,
        )

        departments = await connection.fetch("SELECT id, code, name_en, name_th FROM departments WHERE is_active = TRUE")
        department_by_code = {
            str(record["code"]): {
                "id": str(record["id"]),
                "name_en": record["name_en"],
                "name_th": record["name_th"],
            }
            for record in departments
        }
        department_name_by_id = {
            str(record["id"]): (record["name_th"] if language == "th" and record["name_th"] else record["name_en"])
            for record in departments
        }

        emergency_triggers = await connection.fetch(
            """
            SELECT id, trigger_name, trigger_keywords, condition_json, alert_message_en, alert_message_th, priority
            FROM emergency_triggers
            WHERE is_active = TRUE
            ORDER BY priority ASC, trigger_name ASC
            """
        )
        routing_rules = await connection.fetch(
            """
            SELECT id, department_id, rule_name, symptom_keywords, condition_json, severity_override, priority
            FROM routing_rules
            WHERE is_active = TRUE
            ORDER BY priority ASC, rule_name ASC
            """
        )

        emergency_matches = evaluate_emergency_triggers(
            content,
            [dict(item) for item in emergency_triggers],
            language=language,
        )
        routing_matches = evaluate_routing_rules(content, [dict(item) for item in routing_rules])

        # ----------------------------------------------------------------
        # ADK turn. The HotlineADKRunner owns the InMemorySessionService
        # that holds rolling chat history per session, so there is no DB
        # history fetch here. ``input_mode`` is forwarded as-is so the
        # agents pick the right reply format (voice = short spoken;
        # text = readable prose).
        # ----------------------------------------------------------------
        await self.adk_runner.ensure_adk_session(session_id, language, input_mode)
        adk_result = await self.adk_runner.chat(
            session_id=session_id,
            language=language,
            user_message=content,
            input_mode=input_mode,
        )

        reply = adk_result["reply"]
        new_classification: dict[str, Any] = adk_result.get("classification", {})
        new_contact: dict[str, Any] = adk_result.get("contact", {})

        # Sticky state: if this turn produced a fresh classification use it,
        # otherwise reuse the one from earlier in the conversation. Contact
        # fields accumulate (later turns add patient_name / phone / address
        # one at a time as the EmergencyAgent collects them).
        classification: dict[str, Any] = new_classification or prior_classification
        contact: dict[str, Any] = {**prior_contact, **new_contact}

        # Severity: collapse the ADK five-level system to the legacy
        # 4-bucket schema the DB columns / dashboards / rule engine still
        # speak. If the agent hasn't classified yet (still gathering
        # symptoms), level is missing -> "unknown".
        classification_level = classification.get("level")
        severity_level = (
            _LEVEL_TO_SEVERITY.get(classification_level, "unknown")
            if isinstance(classification_level, int)
            else "unknown"
        )
        severity_confidence: float | None = (
            0.85 if classification.get("classified") else None
        )
        severity_explanation: str | None = classification.get("key_reason")

        # Rule engine overrides -- unchanged. Deterministic matches
        # always win over the LLM, so a known emergency keyword can't
        # be downgraded by a hallucinating agent.
        matched_trigger = emergency_matches[0] if emergency_matches else None
        if matched_trigger:
            severity_level = "emergency"
            if not severity_explanation:
                severity_explanation = matched_trigger.reason

        matched_rule = routing_matches[0] if routing_matches else None
        if matched_rule and matched_rule.severity_override and severity_level != "emergency":
            severity_level = matched_rule.severity_override
            if not severity_explanation:
                severity_explanation = matched_rule.reason

        # Department resolution -- same ladder as before, new source.
        # The ADK classifier returns a department_code via the
        # ``classify_triage_level`` tool.
        adk_dept_code = classification.get("department_code")
        department_id: str | None = None
        department_reason: str | None = None
        department_confidence: float | None = None

        if adk_dept_code and adk_dept_code in department_by_code:
            department_id = department_by_code[adk_dept_code]["id"]
            department_reason = severity_explanation
            department_confidence = severity_confidence
        elif matched_rule and matched_rule.department_id:
            department_id = matched_rule.department_id
            department_reason = matched_rule.reason
            department_confidence = matched_rule.confidence
        elif severity_level == "emergency" and "emergency" in department_by_code:
            department_id = department_by_code["emergency"]["id"]
            department_reason = "Emergency severity requires emergency department"
            department_confidence = 0.95

        emergency_alert_message = (
            matched_trigger.alert_message if matched_trigger else None
        )
        # ADK doesn't emit a structured symptoms list per turn -- the
        # classifier's ``symptoms_summary`` is a sentence. Use it when
        # present, otherwise fall back to the raw user content so the
        # emergency_events row always carries something useful.
        symptoms_summary = classification.get("symptoms_summary")
        detected_symptoms: list[str] = (
            [str(symptoms_summary)] if symptoms_summary else [content]
        )

        model_name = f"adk:{settings.google_model_name}"

        await connection.execute(
            """
            INSERT INTO symptom_entries (
                session_id, message_id, raw_text, normalized_symptoms, body_location, duration_text
            )
            VALUES ($1, $2, $3, $4::jsonb, $5, $6)
            """,
            session_id,
            msg_user["id"],
            content,
            [content],
            None,
            None,
        )

        assessment = await connection.fetchrow(
            """
            INSERT INTO severity_assessments (
                session_id, source_message_id, severity, confidence, explanation, detected_triggers
            )
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            RETURNING id
            """,
            session_id,
            msg_user["id"],
            severity_level,
            severity_confidence,
            severity_explanation,
            [item.name for item in emergency_matches],
        )
        assessment_id = str(assessment["id"]) if assessment else None

        if department_id and assessment_id:
            await connection.execute(
                """
                INSERT INTO department_recommendations (
                    session_id, assessment_id, department_id, confidence, reason
                )
                VALUES ($1, $2, $3, $4, $5)
                """,
                session_id,
                assessment_id,
                department_id,
                department_confidence,
                department_reason,
            )

        if severity_level == "emergency":
            await connection.execute(
                """
                INSERT INTO emergency_events (
                    session_id, trigger_id, source_message_id, detected_symptoms, alert_message
                )
                VALUES ($1, $2, $3, $4::jsonb, $5)
                """,
                session_id,
                matched_trigger.id if matched_trigger else None,
                msg_user["id"],
                detected_symptoms,
                emergency_alert_message
                or ("กรุณาติดต่อเจ้าหน้าที่ทันที" if language == "th" else "Please contact medical staff immediately"),
            )

        # ADK handles follow-up natively inside the agent's reply -- the
        # follow-up question is just part of ``reply`` now, no separate
        # structured field, no follow_up_questions row.
        latency_ms = int((perf_counter() - start) * 1000)

        msg_assistant = await connection.fetchrow(
            """
            INSERT INTO messages (
                session_id, role, input_mode, content, model_name, response_latency_ms, metadata
            )
            VALUES ($1, 'assistant', NULL, $2, $3, $4, '{}'::jsonb)
            RETURNING *
            """,
            session_id,
            reply,
            model_name,
            latency_ms,
        )

        alert_sent = False
        should_notify = await self.notifier.should_send(
            connection,
            session_id,
            severity_level,
            threshold=settings.alert_severity_threshold,
            cooldown_seconds=settings.alert_cooldown_seconds,
        )
        # Gate the actual dispatch on EmergencyAgent having finished its work:
        # the agent collects patient name → phone → address over multiple
        # turns and only sets ``contact_collected=True`` once all three are
        # in hand (via the ``collect_emergency_contact`` tool). Firing before
        # that would send the mock alert with "n/a" placeholders and skip
        # the multi-turn dialogue the user expects.
        contact_ready = bool(contact.get("contact_collected"))
        if should_notify and contact_ready:
            alert = EmergencyAlert(
                session_id=session_id,
                language=language,
                severity=severity_level,
                confidence=severity_confidence,
                department_name=department_name_by_id.get(department_id or ""),
                detected_symptoms=detected_symptoms,
                alert_message=emergency_alert_message,
                patient_name=contact.get("patient_name"),
                phone_number=contact.get("phone_number"),
                address=contact.get("address"),
            )
            alert_sent = await self.notifier.send_alert(alert)

        # Persist the merged triage state on every turn so the next call to
        # ``process_chat`` can rebuild ``classification`` / ``contact`` even
        # if ADK didn't emit a tool output this turn (typical for the middle
        # of the EmergencyAgent name → phone → address handoff). Escalation
        # / alert markers only update on emergency or alert turns.
        existing_metadata = dict(prior_metadata)
        existing_metadata["triage_classification"] = classification
        existing_metadata["emergency_contact"] = contact
        if severity_level == "emergency":
            # Track escalation as soon as the case is classified emergency
            # so dashboards / session.status reflect that immediately,
            # regardless of whether contact has been collected yet.
            existing_metadata["escalation_reason"] = (
                severity_explanation or "Emergency triage match"
            )
        if alert_sent:
            # last_alert_at drives the notifier cooldown -- it MUST only
            # advance when an alert was actually dispatched. If we updated
            # it on every emergency turn (even when contact wasn't ready
            # yet), the EmergencyAgent's later contact-complete turn would
            # be silently suppressed by the cooldown and the mock notifier
            # would never fire.
            existing_metadata["alert_sent"] = True
            existing_metadata["last_alert_at"] = datetime.now(
                timezone.utc
            ).isoformat()
        await connection.execute(
            """
            UPDATE sessions
            SET status = CASE WHEN $2 = 'emergency' THEN 'escalated' ELSE status END,
                ended_at = CASE WHEN $2 = 'emergency' THEN NOW() ELSE ended_at END,
                metadata = $3::jsonb
            WHERE id = $1
            """,
            session_id,
            severity_level,
            existing_metadata,
        )

        result = TriageResult(
            reply=reply,
            severity_level=severity_level,
            severity_explanation=severity_explanation,
            severity_confidence=severity_confidence,
            department_id=department_id,
            department_reason=department_reason,
            department_confidence=department_confidence,
            emergency_trigger_id=matched_trigger.id if matched_trigger else None,
            emergency_alert_message=emergency_alert_message,
            detected_symptoms=detected_symptoms,
            # ADK weaves the follow-up question into ``reply`` itself --
            # there is no longer a separate structured follow-up output.
            follow_up_question=None,
            follow_up_reason=None,
            model_name=model_name,
            latency_ms=latency_ms,
            alert_sent=alert_sent,
        )
        return result, dict(msg_assistant)
