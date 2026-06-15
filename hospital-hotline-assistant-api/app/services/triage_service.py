from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from time import perf_counter
from typing import Any, AsyncIterator

import asyncpg

from app.config import settings
from app.services.notification_service import (
    BaseNotificationService,
    EmergencyAlert,
    MockNotificationService,
)
from app.services.rule_engine import evaluate_emergency_triggers, evaluate_routing_rules
from app.services.triage_engine import LlmTriageEngine, TriageEngine


logger = logging.getLogger(__name__)


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
    def __init__(
        self,
        notifier: BaseNotificationService | None = None,
        triage_engine: TriageEngine | None = None,
    ) -> None:
        self.triage_engine: TriageEngine = triage_engine or LlmTriageEngine()
        # Default to the mock notifier so the demo + tests work without
        # any external transport. Callers can inject a production sink
        # (LINE / FCM / SMS) once those services land.
        self.notifier: BaseNotificationService = notifier or MockNotificationService()

    async def _prepare_chat_turn(
        self,
        *,
        connection: asyncpg.Connection,
        session_id: str,
        language: str,
        input_mode: str,
        content: str,
    ) -> dict[str, Any]:
        """Persist the user turn and load the per-turn reference data.

        Runs the synchronous-feeling first half of a chat turn:
        validates the session, writes the inbound user message, fetches
        the rule-engine inputs (emergency triggers / routing rules /
        departments), and returns a context bag the second half
        (``_finalize_chat_turn``) needs to persist the result. Split out
        of ``process_chat`` so the streaming variant can share it
        verbatim without duplicating fragile DB code.
        """

        session_row = await connection.fetchrow(
            "SELECT id, language, metadata FROM sessions WHERE id = $1",
            session_id,
        )
        if not session_row:
            raise ValueError("Session not found")

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

        departments = await connection.fetch(
            "SELECT id, code, kind, name_en, name_th FROM departments WHERE is_active = TRUE"
        )
        department_by_code = {
            str(record["code"]): {
                "id": str(record["id"]),
                "kind": record["kind"],
                "name_en": record["name_en"],
                "name_th": record["name_th"],
            }
            for record in departments
        }
        department_name_by_id = {
            str(record["id"]): (
                record["name_th"] if language == "th" and record["name_th"] else record["name_en"]
            )
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
        routing_matches = evaluate_routing_rules(
            content, [dict(item) for item in routing_rules]
        )

        await self.triage_engine.ensure_session(
            session_id=session_id,
            language=language,
            input_mode=input_mode,
        )

        return {
            "msg_user": msg_user,
            "prior_metadata": prior_metadata,
            "prior_classification": prior_classification,
            "prior_contact": prior_contact,
            "department_by_code": department_by_code,
            "department_name_by_id": department_name_by_id,
            "emergency_matches": emergency_matches,
            "routing_matches": routing_matches,
        }

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

        ctx = await self._prepare_chat_turn(
            connection=connection,
            session_id=session_id,
            language=language,
            input_mode=input_mode,
            content=content,
        )

        # ----------------------------------------------------------------
        # ADK turn. The HotlineADKRunner owns the InMemorySessionService
        # that holds rolling chat history per session, so there is no DB
        # history fetch here. ``input_mode`` is forwarded as-is so the
        # agents pick the right reply format (voice = short spoken;
        # text = readable prose).
        # ----------------------------------------------------------------
        adk_result = await self.triage_engine.run_turn(
            session_id=session_id,
            language=language,
            input_mode=input_mode,
            content=content,
        )

        return await self._finalize_chat_turn(
            connection=connection,
            session_id=session_id,
            language=language,
            content=content,
            start=start,
            ctx=ctx,
            adk_result=adk_result,
        )

    async def finalize_live_assessment(
        self,
        *,
        connection: asyncpg.Connection,
        session_id: str,
        language: str,
        input_mode: str,
        content: str,
        classification: dict[str, Any],
        contact: dict[str, Any],
        reply: str | None = None,
    ) -> tuple[TriageResult, dict[str, Any]]:
        """Persist a completed live-voice assessment without re-invoking ADK.

        Called when the live pipeline has already collected classification
        (and contact, for emergencies) via tool responses. Skips the
        expensive ``adk_runner.chat`` round-trip and writes the same DB
        rows + staff notifications as a normal chat turn.
        """

        start = perf_counter()
        ctx = await self._prepare_chat_turn(
            connection=connection,
            session_id=session_id,
            language=language,
            input_mode=input_mode,
            content=content,
        )

        agent_reply = (reply or "").strip()
        if not agent_reply:
            level = classification.get("level")
            label = classification.get("label") or ""
            dept = classification.get("department_code") or ""
            if language == "th":
                agent_reply = (
                    f"สรุปการคัดแยก: ระดับ {level} ({label}). "
                    f"แนะนำไปแผนก {dept}."
                    if level
                    else "การประเมินเสร็จสมบูรณ์แล้วค่ะ"
                )
            else:
                agent_reply = (
                    f"Triage complete: Level {level} ({label}). "
                    f"Please proceed to {dept}."
                    if level
                    else "Your assessment is complete."
                )

        adk_result: dict[str, Any] = {
            "reply": agent_reply,
            "classification": classification,
            "contact": contact,
            "input_mode": input_mode,
        }

        result, assistant_message = await self._finalize_chat_turn(
            connection=connection,
            session_id=session_id,
            language=language,
            content=content,
            start=start,
            ctx=ctx,
            adk_result=adk_result,
        )

        await self._notify_staff_assessment_summary(
            connection=connection,
            session_id=session_id,
            language=language,
            result=result,
            classification=classification,
            contact=contact,
        )

        await connection.execute(
            """
            UPDATE sessions
            SET status = CASE
                    WHEN status = 'escalated' THEN status
                    ELSE 'completed'
                END,
                ended_at = COALESCE(ended_at, NOW())
            WHERE id = $1
            """,
            session_id,
        )

        return result, assistant_message

    async def _notify_staff_assessment_summary(
        self,
        *,
        connection: asyncpg.Connection,
        session_id: str,
        language: str,
        result: TriageResult,
        classification: dict[str, Any],
        contact: dict[str, Any],
    ) -> None:
        """Push a staff-facing triage summary when a call completes.

        Emergency dispatch with contact details is handled inside
        :meth:`_finalize_chat_turn` via :meth:`send_alert`. This path
        covers every completed assessment — including non-emergency
        levels — so staff always receive the final result.
        """

        if result.alert_sent:
            return

        dept_name = None
        dept_id = result.department_id
        if dept_id:
            row = await connection.fetchrow(
                "SELECT name_en, name_th FROM departments WHERE id = $1",
                dept_id,
            )
            if row:
                dept_name = (
                    row["name_th"] if language == "th" and row["name_th"] else row["name_en"]
                )

        symptoms_summary = classification.get("symptoms_summary")
        detected = [str(symptoms_summary)] if symptoms_summary else result.detected_symptoms

        level = classification.get("level")
        label = classification.get("label") or ""
        summary_line = result.severity_explanation or classification.get("key_reason")
        if level and label:
            summary_line = f"Level {level} ({label}): {summary_line or 'see session'}"

        alert = EmergencyAlert(
            session_id=session_id,
            language=language,
            severity=result.severity_level,
            confidence=result.severity_confidence,
            department_name=dept_name,
            detected_symptoms=detected,
            alert_message=summary_line,
            patient_name=contact.get("patient_name"),
            phone_number=contact.get("phone_number"),
            address=contact.get("address"),
        )
        await self.notifier.send_assessment_summary(alert)

    async def _finalize_chat_turn(
        self,
        *,
        connection: asyncpg.Connection,
        session_id: str,
        language: str,
        content: str,
        start: float,
        ctx: dict[str, Any],
        adk_result: dict[str, Any],
    ) -> tuple[TriageResult, dict[str, Any]]:
        """Run the post-ADK persistence + rule engine + notification path.

        Identical for streaming and non-streaming callers — they only
        differ in how they obtain ``adk_result``. Pulled out so we
        don't drift between the two: any change to severity collapsing,
        notifier gating, or session-metadata layout lives in one place.
        """

        msg_user = ctx["msg_user"]
        prior_metadata = ctx["prior_metadata"]
        prior_classification = ctx["prior_classification"]
        prior_contact = ctx["prior_contact"]
        department_by_code = ctx["department_by_code"]
        department_name_by_id = ctx["department_name_by_id"]
        emergency_matches = ctx["emergency_matches"]
        routing_matches = ctx["routing_matches"]

        reply = adk_result["reply"]
        new_classification: dict[str, Any] = adk_result.get("classification", {})
        new_contact: dict[str, Any] = adk_result.get("contact", {})

        # Sticky state: if this turn produced a fresh classification use it,
        # otherwise reuse the one from earlier in the conversation. Contact
        # fields accumulate (later turns add patient_name / phone / address
        # one at a time as the EmergencyAgent collects them).
        classification: dict[str, Any] = new_classification or prior_classification
        contact: dict[str, Any] = {**prior_contact, **new_contact}

        # Severity comes from the swappable triage engine so the ADK path
        # and future trained-model path can share the same persistence flow.
        decision = self.triage_engine.decision_from_classification(classification)
        severity_level = decision.severity_level
        severity_confidence: float | None = (
            0.85 if classification.get("classified") else None
        )
        severity_explanation: str | None = decision.key_reason

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

        # Department resolution with MFU OPD-first policy.
        adk_dept_code = decision.opd_department_code
        if severity_level == "emergency":
            adk_dept_code = "emergency"
        elif adk_dept_code and not str(adk_dept_code).startswith("opd_"):
            logger.warning(
                "Non-emergency classification used non-OPD code '%s'; coercing to opd_general",
                adk_dept_code,
            )
            adk_dept_code = "opd_general"

        department_id: str | None = None
        department_reason: str | None = None
        department_confidence: float | None = None

        if adk_dept_code and adk_dept_code in department_by_code:
            department_id = department_by_code[adk_dept_code]["id"]
            department_reason = severity_explanation
            department_confidence = severity_confidence
        elif adk_dept_code:
            logger.warning(
                "Department code '%s' not found in active departments", adk_dept_code
            )
        elif matched_rule and matched_rule.department_id:
            matched_kind = next(
                (
                    item["kind"]
                    for item in department_by_code.values()
                    if item["id"] == matched_rule.department_id
                ),
                None,
            )
            if severity_level != "emergency" and matched_kind != "opd":
                logger.warning(
                    "Routing rule selected non-OPD department '%s' for non-emergency; skipping",
                    matched_rule.department_id,
                )
            else:
                department_id = matched_rule.department_id
                department_reason = matched_rule.reason
                department_confidence = matched_rule.confidence
        elif severity_level == "emergency" and "emergency" in department_by_code:
            department_id = department_by_code["emergency"]["id"]
            department_reason = "Emergency severity requires emergency department"
            department_confidence = 0.95
        elif "opd_general" in department_by_code:
            department_id = department_by_code["opd_general"]["id"]
            department_reason = "OPD-first default routing for non-emergency assessment"
            department_confidence = 0.6

        emergency_alert_message = (
            matched_trigger.alert_message if matched_trigger else None
        )
        # ADK doesn't emit a structured symptoms list per turn -- the
        # classifier's ``symptoms_summary`` is a sentence. Use it when
        # present, otherwise fall back to the raw user content so the
        # emergency_events row always carries something useful.
        symptoms_summary = decision.symptoms_summary
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

        if assessment_id:
            await connection.execute(
                """
                INSERT INTO assessment_reviews (
                    session_id, assessment_id, proposed_department_id, status
                )
                VALUES ($1, $2, $3, 'pending')
                ON CONFLICT (assessment_id) DO UPDATE
                SET proposed_department_id = EXCLUDED.proposed_department_id,
                    updated_at = NOW()
                """,
                session_id,
                assessment_id,
                department_id,
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

    async def process_chat_stream(
        self,
        *,
        connection: asyncpg.Connection,
        session_id: str,
        language: str,
        input_mode: str,
        content: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Streaming variant of :meth:`process_chat`.

        Yields a sequence of event dicts that the HTTP layer can relay
        to the frontend as Server-Sent Events. Mirrors the
        non-streaming path's persistence + rule-engine + notifier
        behaviour exactly — same DB writes, same notifier gating, same
        sticky-state semantics — only the agent text reaches the
        client incrementally instead of all at once.

        Emitted event types:
        * ``{"type": "user_message", "message": {...}}`` once the
          inbound user message is persisted (so the UI can re-render
          its optimistic bubble with the real DB id + timestamp).
        * ``{"type": "delta", "text": "..."}`` as the agent streams.
        * ``{"type": "classified", ...}`` / ``{"type": "contact", ...}``
          when the respective tool fires.
        * ``{"type": "complete", "result": {...},
            "assistant_message": {...}}`` terminal event with the full
          TriageResult payload (matches the existing /chat response
          shape) and the freshly-persisted assistant DB row.
        * ``{"type": "error", "message": "..."}`` on a fatal failure.
        """

        start = perf_counter()

        try:
            ctx = await self._prepare_chat_turn(
                connection=connection,
                session_id=session_id,
                language=language,
                input_mode=input_mode,
                content=content,
            )
        except ValueError as exc:
            yield {"type": "error", "message": str(exc)}
            return

        # Echo the persisted user message so the frontend can swap its
        # optimistic bubble for the real DB row (id, timestamp). The
        # asyncpg Record is dict-castable; we coerce so JSON encoding
        # downstream is straightforward.
        yield {"type": "user_message", "message": dict(ctx["msg_user"])}

        # Consume the ADK stream. We accumulate the reply locally as
        # we go so that the final ``adk_result`` we feed into
        # ``_finalize_chat_turn`` has the same shape the non-streaming
        # path expects, even though the text arrived in deltas.
        adk_result: dict[str, Any] = {
            "reply": "",
            "classification": {},
            "contact": {},
            "input_mode": input_mode,
        }
        try:
            async for event in self.triage_engine.run_turn_stream(
                session_id=session_id,
                language=language,
                input_mode=input_mode,
                content=content,
            ):
                event_type = event.get("type")
                if event_type == "delta":
                    yield {"type": "delta", "text": event["text"]}
                elif event_type == "reset":
                    # Inner LLM call ended in a tool dispatch — its
                    # deltas were reasoning, not the actual reply.
                    # Forward so the frontend wipes the bubble and
                    # the TTS queue can drop already-queued chunks.
                    yield {"type": "reset"}
                elif event_type == "classified":
                    adk_result["classification"] = event["classification"]
                    yield event
                elif event_type == "contact":
                    adk_result["contact"] = event["contact"]
                    yield event
                elif event_type == "done":
                    adk_result["reply"] = event.get("reply", "")
                    # Refresh classification/contact in case the agent
                    # tool fired only inside the aggregated final event
                    # (which we explicitly forward through ``done``).
                    adk_result["classification"] = (
                        event.get("classification")
                        or adk_result["classification"]
                    )
                    adk_result["contact"] = (
                        event.get("contact") or adk_result["contact"]
                    )
        except Exception as exc:
            yield {"type": "error", "message": f"agent_stream_failed: {exc}"}
            return

        try:
            result, assistant_message = await self._finalize_chat_turn(
                connection=connection,
                session_id=session_id,
                language=language,
                content=content,
                start=start,
                ctx=ctx,
                adk_result=adk_result,
            )
        except Exception as exc:
            yield {"type": "error", "message": f"finalize_failed: {exc}"}
            return

        yield {
            "type": "complete",
            "result": _triage_result_to_payload(result),
            "assistant_message": assistant_message,
        }


def _triage_result_to_payload(result: TriageResult) -> dict[str, Any]:
    """Coerce :class:`TriageResult` into the same JSON shape the
    existing ``/sessions/{id}/chat`` REST response uses.

    Keeping the schema identical between streaming and non-streaming
    means the frontend can re-use its existing ``ChatResponsePayload``
    parser for the terminal ``complete`` event.
    """

    return {
        "reply": result.reply,
        "severity": {
            "level": result.severity_level,
            "explanation": result.severity_explanation,
            "confidence": result.severity_confidence,
        },
        "department": (
            {
                "department_id": result.department_id,
                "reason": result.department_reason,
                "confidence": result.department_confidence,
            }
            if result.department_id
            else None
        ),
        "emergency": (
            {
                "trigger_id": result.emergency_trigger_id,
                "alert_message": result.emergency_alert_message,
                "detected_symptoms": result.detected_symptoms,
            }
            if result.emergency_trigger_id or result.emergency_alert_message
            else None
        ),
        "symptoms": None,
        "follow_up_question": result.follow_up_question,
        "follow_up_reason": result.follow_up_reason,
        "alert_sent": result.alert_sent,
        "model_name": result.model_name,
        "latency_ms": result.latency_ms,
    }
