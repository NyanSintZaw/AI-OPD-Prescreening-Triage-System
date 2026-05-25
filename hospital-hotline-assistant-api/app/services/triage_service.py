from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

import asyncpg

from app.services.google_ai import GoogleTriageClient
from app.services.rule_engine import evaluate_emergency_triggers, evaluate_routing_rules
from app.services.slack_notifier import SlackNotifier


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
    def __init__(self) -> None:
        self.google_client = GoogleTriageClient()
        self.slack_notifier = SlackNotifier()

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

        history_rows = await connection.fetch(
            """
            SELECT role, content, created_at
            FROM messages
            WHERE session_id = $1
            ORDER BY created_at ASC
            LIMIT 20
            """,
            session_id,
        )
        history = [dict(item) for item in history_rows]

        ai_payload = await self.google_client.generate_triage(
            language=language,
            user_message=content,
            history=history,
            emergency_context=[item.name for item in emergency_matches],
            routing_context=[item.name for item in routing_matches],
            input_mode=input_mode,
        )

        severity_level = str(ai_payload.get("severity", {}).get("level") or "unknown")
        severity_explanation = ai_payload.get("severity", {}).get("explanation")
        severity_confidence = ai_payload.get("severity", {}).get("confidence")

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

        ai_department_code = (ai_payload.get("department", {}) or {}).get("code")
        department_id: str | None = None
        department_reason = (ai_payload.get("department", {}) or {}).get("reason")
        department_confidence = (ai_payload.get("department", {}) or {}).get("confidence")

        if ai_department_code and ai_department_code in department_by_code:
            department_id = department_by_code[ai_department_code]["id"]
        elif matched_rule and matched_rule.department_id:
            department_id = matched_rule.department_id
            department_reason = department_reason or matched_rule.reason
            department_confidence = department_confidence or matched_rule.confidence
        elif severity_level == "emergency" and "emergency" in department_by_code:
            department_id = department_by_code["emergency"]["id"]
            department_reason = department_reason or "Emergency severity requires emergency department"
            department_confidence = department_confidence or 0.95

        emergency_alert_message = (
            matched_trigger.alert_message
            if matched_trigger
            else (ai_payload.get("emergency") or {}).get("alertMessage")
        )
        detected_symptoms = (
            list((ai_payload.get("emergency") or {}).get("detectedSymptoms") or []) or [content]
        )

        model_name = ai_payload.get("modelName") or "google-triage"

        symptom_payload = ai_payload.get("symptoms") or {}
        await connection.execute(
            """
            INSERT INTO symptom_entries (
                session_id, message_id, raw_text, normalized_symptoms, body_location, duration_text
            )
            VALUES ($1, $2, $3, $4::jsonb, $5, $6)
            """,
            session_id,
            msg_user["id"],
            str(symptom_payload.get("rawText") or content),
            [content],
            symptom_payload.get("bodyLocation"),
            symptom_payload.get("durationText"),
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

        follow_up_question = ai_payload.get("followUpQuestion")
        follow_up_reason = ai_payload.get("followUpReason")
        if ai_payload.get("needsFollowUp") and follow_up_question:
            await connection.execute(
                """
                INSERT INTO follow_up_questions (session_id, question_text, reason)
                VALUES ($1, $2, $3)
                """,
                session_id,
                follow_up_question,
                follow_up_reason,
            )

        reply = str(ai_payload.get("reply") or "")
        if not reply:
            reply = (
                "กรุณาให้รายละเอียดเพิ่มเติมเกี่ยวกับอาการเพื่อประเมินระดับความเร่งด่วน"
                if language == "th"
                else "Please provide more details about your symptoms for accurate triage."
            )

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
        if await self.slack_notifier.should_send(connection, session_id, severity_level):
            alert_sent = await self.slack_notifier.send_alert(
                session_id=session_id,
                language=language,
                user_message=content,
                severity=severity_level,
                confidence=float(severity_confidence) if severity_confidence is not None else None,
                department_name=department_name_by_id.get(department_id or ""),
                emergency_reason=severity_explanation,
                alert_message=emergency_alert_message,
            )

        if severity_level == "emergency" or alert_sent:
            existing_metadata = dict(session_row["metadata"] or {})
            existing_metadata.update(
                {
                    "alert_sent": alert_sent or existing_metadata.get("alert_sent", False),
                    "last_alert_at": datetime.now(timezone.utc).isoformat(),
                    "escalation_reason": severity_explanation or "Emergency triage match",
                }
            )
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
            severity_confidence=float(severity_confidence) if severity_confidence is not None else None,
            department_id=department_id,
            department_reason=department_reason,
            department_confidence=float(department_confidence) if department_confidence is not None else None,
            emergency_trigger_id=matched_trigger.id if matched_trigger else None,
            emergency_alert_message=emergency_alert_message,
            detected_symptoms=detected_symptoms,
            follow_up_question=follow_up_question if ai_payload.get("needsFollowUp") else None,
            follow_up_reason=follow_up_reason if ai_payload.get("needsFollowUp") else None,
            model_name=model_name,
            latency_ms=latency_ms,
            alert_sent=alert_sent,
        )
        return result, dict(msg_assistant)
