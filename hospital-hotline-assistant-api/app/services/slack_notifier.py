from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import asyncpg
import httpx

from app.config import settings


SEVERITY_ORDER = {
    "unknown": 0,
    "general": 1,
    "urgent": 2,
    "emergency": 3,
}


class SlackNotifier:
    async def should_send(
        self,
        connection: asyncpg.Connection,
        session_id: str,
        severity: str,
    ) -> bool:
        threshold_level = SEVERITY_ORDER.get(settings.alert_severity_threshold, 3)
        current_level = SEVERITY_ORDER.get(severity, 0)
        if current_level < threshold_level:
            return False

        if not settings.slack_webhook_url:
            return False

        row = await connection.fetchrow("SELECT metadata FROM sessions WHERE id = $1", session_id)
        if not row:
            return False

        metadata = row.get("metadata") or {}
        last_alert = metadata.get("last_alert_at")
        if not last_alert:
            return True

        try:
            last_dt = datetime.fromisoformat(last_alert.replace("Z", "+00:00"))
        except ValueError:
            return True

        delta = datetime.now(timezone.utc) - last_dt
        return delta.total_seconds() >= settings.alert_cooldown_seconds

    async def send_alert(
        self,
        *,
        session_id: str,
        language: str,
        user_message: str,
        severity: str,
        confidence: float | None,
        department_name: str | None,
        emergency_reason: str | None,
        alert_message: str | None,
    ) -> bool:
        if not settings.slack_webhook_url:
            return False

        payload: dict[str, Any] = {
            "text": f"Hospital Hotline Alert - {severity.upper()}",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"Hotline Alert: {severity.upper()}"},
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Session:*\n`{session_id}`"},
                        {"type": "mrkdwn", "text": f"*Language:*\n{language}"},
                        {"type": "mrkdwn", "text": f"*Severity:*\n{severity}"},
                        {"type": "mrkdwn", "text": f"*Confidence:*\n{confidence if confidence is not None else 'n/a'}"},
                        {"type": "mrkdwn", "text": f"*Department:*\n{department_name or 'n/a'}"},
                        {"type": "mrkdwn", "text": f"*Reason:*\n{emergency_reason or 'n/a'}"},
                    ],
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Latest User Message:*\n{user_message}"},
                },
            ],
        }
        if alert_message:
            payload["blocks"].append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Alert message:*\n{alert_message}"},
                }
            )

        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.post(settings.slack_webhook_url, json=payload)
            return response.status_code < 300
