from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any, AsyncIterator

import asyncpg

from app.config import settings
from app.services.ai.triage_models import TriageResult
from app.services.ai.triage_payloads import _triage_result_to_payload
from app.services.notification_service import (
    BaseNotificationService,
    EmergencyAlert,
    MockNotificationService,
)
from app.services.rule_engine import (
    evaluate_emergency_triggers,
    evaluate_routing_rules,
    evaluate_scale_override,
)
from app.services.triage_engine import LlmTriageEngine, TriageEngine


logger = logging.getLogger(__name__)

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


async def _build_schedule_context(connection: asyncpg.Connection) -> str | None:
    """Fetch today's available doctor schedules and format them as a short
    context block injected into the AI's message prefix.

    Only entries with schedule_date = today are surfaced; historical rows
    remain in the DB for audit purposes but are invisible here.
    Returns None when the doctors table doesn't exist yet (pre-migration).
    """
    from datetime import date, datetime, timezone

    today = date.today()
    today_name = today.strftime("%A, %d %B %Y")

    try:
        rows = await connection.fetch(
            """
            SELECT d.full_name, d.title, d.specialization,
                   dept.name_en AS dept_name,
                   s.start_time, s.end_time, s.break_start, s.break_end,
                   s.room, s.slot_label
            FROM doctors d
            LEFT JOIN departments dept ON dept.id = d.department_id
            JOIN doctor_schedules s ON s.doctor_id = d.id
            WHERE d.is_active = TRUE
              AND s.schedule_date = $1
              AND s.is_available = TRUE
            ORDER BY d.full_name, s.start_time
            """,
            today,
        )
    except Exception:
        return None

    if not rows:
        return f"[SCHEDULE: Today is {today_name}. No doctors are scheduled today.]"

    lines = [f"[SCHEDULE: Today is {today_name}. Available doctors:"]
    for row in rows:
        slot = f"{row['start_time'].strftime('%H:%M')}–{row['end_time'].strftime('%H:%M')}"
        if row['break_start'] and row['break_end']:
            slot += f" (break {row['break_start'].strftime('%H:%M')}–{row['break_end'].strftime('%H:%M')})"
        label = f" [{row['slot_label']}]" if row['slot_label'] else ""
        room = f", Room {row['room']}" if row['room'] else ""
        dept = f", {row['dept_name']}" if row['dept_name'] else ""
        spec = f" — {row['specialization']}" if row['specialization'] else ""
        lines.append(f"  • {row['title']} {row['full_name']}{spec}{dept}{room}: {slot}{label}")
    lines.append(
        "If a patient asks about available doctors or doctor schedules, "
        "answer using only this information. Do not guess or invent schedules.]"
    )
    return "\n".join(lines)


def _classification_score(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        score = int(value)
    except (TypeError, ValueError):
        return None
    return score if 0 <= score <= 10 else None


def _classification_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _vitals_context(metadata: dict[str, Any]) -> str | None:
    """Render session-stored vitals (kiosk cuff / manual entry) as a
    bracketed context line for the agent, mirroring the ``[SCHEDULE: ...]``
    and ``[PHASE: ...]`` injection convention. Returns None when the
    session has no usable blood-pressure reading."""

    vitals = metadata.get("vitals") or {}
    systolic = vitals.get("systolic")
    diastolic = vitals.get("diastolic")
    if not systolic or not diastolic:
        return None
    parts = [f"blood pressure {systolic}/{diastolic} mmHg"]
    if vitals.get("pulse_bpm"):
        parts.append(f"pulse {vitals['pulse_bpm']} bpm")
    if vitals.get("measured_at"):
        parts.append(f"measured at {vitals['measured_at']}")
    source = vitals.get("source")
    if source:
        parts.append(
            "source: kiosk cuff" if source == "device" else "source: patient-reported"
        )
    return (
        "[PATIENT_VITALS: "
        + ", ".join(parts)
        + " — factor these vitals into the triage decision and do not ask "
        "the patient to measure their blood pressure again.]"
    )


def _classification_red_flags(value: Any) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    return [str(item).strip() for item in items if str(item).strip()]


class TriageService:
    def __init__(
        self,
        notifier: BaseNotificationService | None = None,
        triage_engine: TriageEngine | None = None,
    ) -> None:
        self.triage_engine: TriageEngine = triage_engine or LlmTriageEngine()
        # Default to the mock notifier so the demo + tests work without
        # any external transport. Callers can inject a production sink
        # real staff-summary channel once one is configured.
        self.notifier: BaseNotificationService = notifier or MockNotificationService()

    async def _prepare_chat_turn(
        self,
        *,
        connection: asyncpg.Connection,
        session_id: str,
        language: str,
        input_mode: str,
        content: str,
        persist_user_message: bool = True,
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

        msg_user = None
        if persist_user_message:
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

        schedule_context = await _build_schedule_context(connection)

        return {
            "msg_user": msg_user,
            "prior_metadata": prior_metadata,
            "prior_classification": prior_classification,
            "prior_contact": {},
            "department_by_code": department_by_code,
            "department_name_by_id": department_name_by_id,
            "emergency_matches": emergency_matches,
            "routing_matches": routing_matches,
            "schedule_context": schedule_context,
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
        agent_content = content
        vitals_line = _vitals_context(ctx["prior_metadata"])
        if vitals_line:
            agent_content = f"{vitals_line}\n{content}"

        adk_result = await self.triage_engine.run_turn(
            session_id=session_id,
            language=language,
            input_mode=input_mode,
            content=agent_content,
            schedule_context=ctx.get("schedule_context"),
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
        live_messages: list[dict[str, Any]] | None = None,
    ) -> tuple[TriageResult, dict[str, Any]]:
        """Persist a completed live-voice assessment without re-invoking ADK.

        Called when the live pipeline has already collected classification
        via tool responses. Skips the
        expensive ``adk_runner.chat`` round-trip and writes the same DB
        rows + staff notifications as a normal chat turn.
        """

        start = perf_counter()
        segmented_live_messages = self._normalize_live_messages(live_messages or [])

        ctx = await self._prepare_chat_turn(
            connection=connection,
            session_id=session_id,
            language=language,
            input_mode=input_mode,
            content=content,
            persist_user_message=not segmented_live_messages,
        )

        agent_reply = (reply or "").strip()
        if not agent_reply:
            # Patients never see the triage level — department guidance only.
            dept = classification.get("department_code") or ""
            if language == "th":
                agent_reply = (
                    f"การประเมินเสร็จสมบูรณ์แล้วค่ะ กรุณาไปที่แผนก {dept} นะคะ"
                    if dept
                    else "การประเมินเสร็จสมบูรณ์แล้วค่ะ"
                )
            else:
                agent_reply = (
                    f"Your assessment is complete. Please proceed to {dept}."
                    if dept
                    else "Your assessment is complete."
                )

        adk_result: dict[str, Any] = {
            "reply": agent_reply,
            "classification": classification,
            "contact": contact,
            "input_mode": input_mode,
        }

        if segmented_live_messages:
            persisted_messages = await self._persist_live_messages(
                connection=connection,
                session_id=session_id,
                messages=segmented_live_messages,
            )
            first_user_message = next(
                (
                    message
                    for message in persisted_messages
                    if message.get("role") == "user"
                ),
                None,
            )
            last_assistant_message = next(
                (
                    message
                    for message in reversed(persisted_messages)
                    if message.get("role") == "assistant"
                ),
                None,
            )
            if first_user_message is None:
                first_user_message = await connection.fetchrow(
                    """
                    INSERT INTO messages (session_id, role, input_mode, content, metadata)
                    VALUES ($1, 'user', $2, $3, $4::jsonb)
                    RETURNING *
                    """,
                    session_id,
                    input_mode,
                    content or "[voice call]",
                    {"source": "live_voice", "aggregate_fallback": True},
                )
                first_user_message = dict(first_user_message)
            ctx["msg_user"] = first_user_message
            ctx["assistant_message_override"] = last_assistant_message

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

    def _normalize_live_messages(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Clean and coalesce live transcript events for DB display rows."""

        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(messages):
            role = item.get("role")
            if role == "agent":
                role = "assistant"
            if role not in {"user", "assistant"}:
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            input_mode = item.get("input_mode") or (
                "voice" if role == "user" else None
            )
            sequence = item.get("sequence")
            if not isinstance(sequence, int):
                sequence = index

            if normalized and normalized[-1]["role"] == role:
                previous = normalized[-1]["content"]
                separator = "" if previous.endswith((" ", "\n")) else " "
                normalized[-1]["content"] = f"{previous}{separator}{content}".strip()
                normalized[-1]["sequence_end"] = sequence
                continue

            normalized.append(
                {
                    "role": role,
                    "input_mode": input_mode,
                    "content": content,
                    "sequence": sequence,
                    "sequence_end": sequence,
                }
            )
        return normalized

    async def _persist_live_messages(
        self,
        *,
        connection: asyncpg.Connection,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Persist a live call transcript as chronological message rows."""

        persisted: list[dict[str, Any]] = []
        base_time = datetime.now(timezone.utc)
        for index, message in enumerate(messages):
            metadata = {
                "source": "live_voice",
                "sequence": message.get("sequence", index),
                "sequence_end": message.get(
                    "sequence_end",
                    message.get("sequence", index),
                ),
            }
            record = await connection.fetchrow(
                """
                INSERT INTO messages (
                    session_id, role, input_mode, content, created_at, metadata
                )
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                RETURNING *
                """,
                session_id,
                message["role"],
                message.get("input_mode"),
                message["content"],
                base_time + timedelta(milliseconds=index),
                metadata,
            )
            persisted.append(dict(record))
        return persisted

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

        This path covers every completed assessment — including
        emergency levels — so staff always receive the final result.
        """

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
        department_by_code = ctx["department_by_code"]
        department_name_by_id = ctx["department_name_by_id"]
        emergency_matches = ctx["emergency_matches"]
        routing_matches = ctx["routing_matches"]

        reply = adk_result["reply"]
        new_classification: dict[str, Any] = adk_result.get("classification", {})
        # Sticky state: if this turn produced a fresh classification use it,
        # otherwise reuse the one from earlier in the conversation.
        classification: dict[str, Any] = new_classification or prior_classification
        contact: dict[str, Any] = adk_result.get("contact", {}) or {}

        # Severity comes from the swappable triage engine so the ADK path
        # and future trained-model path can share the same persistence flow.
        decision = self.triage_engine.decision_from_classification(classification)
        severity_level = decision.severity_level
        severity_confidence: float | None = (
            0.85 if classification.get("classified") else None
        )
        severity_explanation: str | None = decision.key_reason

        pain_score = _classification_score(classification.get("pain_score"))
        pain_location = _classification_text(classification.get("pain_location"))
        distress_score = _classification_score(classification.get("distress_score"))
        distress_type = _classification_text(classification.get("distress_type"))
        red_flags = _classification_red_flags(classification.get("red_flags"))

        # Override order: ADK decision -> emergency keyword trigger ->
        # routing rule -> pain/distress scale. Later rules may escalate
        # acuity, but nothing can downgrade an existing emergency.
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

        scale_override = evaluate_scale_override(classification, severity_level)
        if scale_override.severity and severity_level != "emergency":
            severity_level = scale_override.severity
            if scale_override.reason:
                severity_explanation = scale_override.reason

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

        emergency_alert_message = None
        # ADK doesn't emit a structured symptoms list per turn -- the
        # classifier's ``symptoms_summary`` is a sentence. Use it when
        # present, otherwise fall back to the raw user content so the
        # emergency_events row always carries something useful.
        symptoms_summary = decision.symptoms_summary
        detected_symptoms: list[str] = (
            [str(symptoms_summary)] if symptoms_summary else [content]
        )

        model_name = adk_result.get("model_name") or f"adk:{settings.google_model_name}"

        await connection.execute(
            """
            INSERT INTO symptom_entries (
                session_id, message_id, raw_text, normalized_symptoms,
                body_location, duration_text, pain_score, pain_location,
                distress_score, distress_type, red_flags
            )
            VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, $9, $10, $11::jsonb)
            """,
            session_id,
            msg_user["id"],
            content,
            [content],
            None,
            None,
            pain_score,
            pain_location,
            distress_score,
            distress_type,
            red_flags,
        )

        # ── Disease Surveillance Capture ──────────────────────────────────
        # Build surveillance keywords from three sources (in priority order):
        #   1. AI classify_triage_level output  → red_flags + symptoms_summary
        #   2. Routing rule keyword matches      → structured symptom keywords
        #   3. Emergency trigger keyword matches → structured trigger keywords
        # We upsert one row per session so the record improves as the
        # conversation progresses without creating duplicates.
        surv_keywords: list[str] = []
        surv_summary: str | None = None

        if new_classification.get("classified") is True:
            # Best-quality: AI explicitly classified the case.
            surv_keywords = list(red_flags)
            surv_summary = _classification_text(new_classification.get("symptoms_summary"))
            if surv_summary and surv_summary not in surv_keywords:
                surv_keywords.append(surv_summary)
        else:
            # Fallback: extract keywords from routing-rule / emergency-trigger
            # matches so even short conversations produce surveillance data.
            for rule in routing_matches:
                for kw in (rule.keywords or []):
                    if kw and kw not in surv_keywords:
                        surv_keywords.append(kw)
            for trigger in emergency_matches:
                for kw in (trigger.keywords or []):
                    if kw and kw not in surv_keywords:
                        surv_keywords.append(kw)

        if surv_keywords or surv_summary:
            try:
                location_area = await connection.fetchval(
                    "SELECT location_area FROM sessions WHERE id = $1",
                    session_id,
                )
                await connection.execute(
                    """
                    INSERT INTO disease_surveillance
                        (session_id, symptom_keywords, symptoms_summary,
                         severity_level, location_area)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (session_id) DO UPDATE
                        SET symptom_keywords = EXCLUDED.symptom_keywords,
                            symptoms_summary = COALESCE(EXCLUDED.symptoms_summary, disease_surveillance.symptoms_summary),
                            severity_level   = EXCLUDED.severity_level,
                            location_area    = COALESCE(EXCLUDED.location_area, disease_surveillance.location_area),
                            reported_at      = NOW()
                    """,
                    session_id,
                    surv_keywords,
                    surv_summary,
                    severity_level,
                    location_area,
                )
            except Exception as exc:
                logger.warning("disease_surveillance upsert failed: %s", exc)

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

        # ADK handles follow-up natively inside the agent's reply -- the
        # follow-up question is just part of ``reply`` now, no separate
        # structured field, no follow_up_questions row.
        latency_ms = int((perf_counter() - start) * 1000)

        msg_assistant = ctx.get("assistant_message_override")
        if msg_assistant is None:
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

        # Persist the merged triage state on every turn so the next call to
        # ``process_chat`` can rebuild ``classification`` even if ADK didn't
        # emit a tool output this turn.
        existing_metadata = dict(prior_metadata)
        existing_metadata["triage_classification"] = classification
        if "requested" in contact:
            existing_metadata["patient_contact_requested"] = contact.get("requested")
            existing_metadata["patient_contact_phone"] = contact.get("phone")
            existing_metadata["patient_contact_preferred_time"] = contact.get(
                "preferred_time"
            )
            existing_metadata["patient_contact_relation"] = contact.get("relation")
            existing_metadata["patient_contact_updated_at"] = datetime.now(
                timezone.utc
            ).isoformat()
        if severity_level == "emergency":
            existing_metadata["escalation_reason"] = (
                severity_explanation or "Emergency triage match"
            )
        await connection.execute(
            """
            UPDATE sessions
            SET metadata = $2::jsonb
            WHERE id = $1
            """,
            session_id,
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
            raw_text=content,
            pain_score=pain_score,
            pain_location=pain_location,
            distress_score=distress_score,
            distress_type=distress_type,
            red_flags=red_flags,
            contact=contact,
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
        * ``{"type": "classified", ...}`` when the triage tool fires.
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

        prior_metadata = dict(ctx["prior_metadata"])
        contact_flow = str(prior_metadata.get("contact_flow") or "idle")
        is_contact_turn = contact_flow in {"awaiting_consent", "awaiting_phone"}
        agent_content = content
        if is_contact_turn:
            agent_content = (
                "[PHASE: contact_preference]\n"
                f"[CONTACT_FLOW: {contact_flow}]\n"
                f"{content}"
            )
        vitals_line = _vitals_context(prior_metadata)
        if vitals_line:
            agent_content = f"{vitals_line}\n{agent_content}"

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
                content=agent_content,
                schedule_context=ctx.get("schedule_context"),
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
                elif event_type == "done":
                    adk_result["reply"] = event.get("reply", "")
                    # Refresh classification in case the agent
                    # tool fired only inside the aggregated final event
                    # (which we explicitly forward through ``done``).
                    adk_result["classification"] = (
                        event.get("classification")
                        or adk_result["classification"]
                    )
                    adk_result["contact"] = event.get("contact") or adk_result["contact"]
        except Exception as exc:
            yield {"type": "error", "message": f"agent_stream_failed: {exc}"}
            return

        contact = adk_result.get("contact") or {}
        if is_contact_turn:
            requested = contact.get("requested")
            needs_followup = contact.get("needs_followup") is True
            next_flow = contact_flow
            if needs_followup:
                next_flow = "awaiting_phone" if requested is True else "awaiting_consent"
            else:
                next_flow = "done"
            prior_metadata.update(
                {
                    "contact_flow": next_flow,
                    "patient_contact_requested": requested,
                    "patient_contact_phone": contact.get("phone_number"),
                    "patient_contact_preferred_time": contact.get("preferred_time"),
                    "patient_contact_relation": contact.get("relation"),
                    "patient_contact_updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            await connection.execute(
                "UPDATE sessions SET metadata = $2::jsonb WHERE id = $1",
                session_id,
                prior_metadata,
            )

            if needs_followup:
                assistant_message = await self._persist_assistant_message(
                    connection=connection,
                    session_id=session_id,
                    reply=adk_result["reply"],
                    start=start,
                    model_name=adk_result.get("model_name"),
                )
                yield {
                    "type": "turn_complete",
                    "assistant_message": assistant_message,
                    "awaiting_contact": True,
                }
                return

            adk_result["classification"] = prior_metadata.get("triage_classification") or {}
            content = str(prior_metadata.get("triage_content") or content)

        elif adk_result.get("classification", {}).get("classified") is True:
            prior_metadata["triage_classification"] = adk_result["classification"]
            prior_metadata["triage_content"] = content
            prior_metadata["contact_flow"] = "awaiting_consent"
            await connection.execute(
                "UPDATE sessions SET metadata = $2::jsonb WHERE id = $1",
                session_id,
                prior_metadata,
            )
            assistant_message = await self._persist_assistant_message(
                connection=connection,
                session_id=session_id,
                reply=adk_result["reply"],
                start=start,
                model_name=adk_result.get("model_name"),
            )
            yield {
                "type": "turn_complete",
                "assistant_message": assistant_message,
                "awaiting_contact": True,
            }
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

    async def _persist_assistant_message(
        self,
        *,
        connection: asyncpg.Connection,
        session_id: str,
        reply: str,
        start: float,
        model_name: str | None = None,
    ) -> dict[str, Any]:
        latency_ms = int((perf_counter() - start) * 1000)
        model_name = model_name or f"adk:{settings.google_model_name}"
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
        return dict(msg_assistant)
