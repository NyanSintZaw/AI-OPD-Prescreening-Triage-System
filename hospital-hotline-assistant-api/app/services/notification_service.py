"""Notification service abstraction for emergency dispatches.

Replaces the deleted ``slack_notifier.py``. The interface lets the
demo route alerts to stdout (:class:`MockNotificationService`) while
production can swap in a LINE / FCM / SMS sender without changing
any call sites.

The ``should_send`` cooldown / threshold logic lives on the base
class because every backend wants the same debounce semantics --
only ``send_alert`` varies per transport. Both ``threshold`` and
``cooldown_seconds`` are passed in explicitly (rather than read
from ``settings``) so the method is trivially testable and call
sites can override per-flow if needed.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone

import asyncpg

logger = logging.getLogger(__name__)


# Ordered ladder used by ``should_send`` to compare a session's
# current severity against the configured dispatch threshold. The
# numbers are intentionally arbitrary -- only the relative order
# matters. Keep in sync with :data:`app.schemas.SeverityLevel`.
SEVERITY_ORDER: dict[str, int] = {
    "unknown": 0,
    "general": 1,
    "urgent": 2,
    "emergency": 3,
}


@dataclass(slots=True)
class EmergencyAlert:
    """Structured payload handed to every notification backend.

    Triage fields (``severity``, ``confidence``, ``department_name``,
    ``detected_symptoms``, ``alert_message``) are produced by the
    triage agent. The PII fields (``patient_name``, ``phone_number``,
    ``address``) are populated by the EmergencyAgent only after the
    patient submits the secure form -- they stay ``None`` for
    non-PII alerts (dashboards, audit log, etc.) so the same shape
    can be reused everywhere.
    """

    session_id: str
    language: str
    severity: str
    confidence: float | None = None
    department_name: str | None = None
    detected_symptoms: list[str] = field(default_factory=list)
    alert_message: str | None = None
    patient_name: str | None = None
    phone_number: str | None = None
    address: str | None = None


class BaseNotificationService(ABC):
    """Abstract notifier with shared debounce / threshold gating.

    Subclasses MUST implement :meth:`send_alert`. They SHOULD NOT
    override :meth:`should_send` -- the cooldown rule is a shared
    contract, not transport-specific policy. If a backend needs an
    additional "can I actually dispatch right now?" check (e.g. a
    webhook URL must be configured), do it inside ``send_alert``
    and return ``False`` on misconfiguration so the caller can
    treat it as a soft failure.
    """

    async def should_send(
        self,
        connection: asyncpg.Connection,
        session_id: str,
        severity: str,
        threshold: str,
        cooldown_seconds: int,
    ) -> bool:
        """Return True if an alert for ``severity`` should be dispatched now.

        Mirrors the original ``SlackNotifier.should_send`` behaviour:

        * Reject anything below ``threshold`` on the severity ladder.
        * Allow if the session has never alerted before.
        * Otherwise allow only if ``cooldown_seconds`` have elapsed
          since ``sessions.metadata.last_alert_at``.

        Unknown / malformed ``last_alert_at`` values are treated as
        "never alerted" rather than raising -- the goal is to never
        block a real emergency on bad bookkeeping.
        """

        threshold_level = SEVERITY_ORDER.get(threshold, 3)
        current_level = SEVERITY_ORDER.get(severity, 0)
        if current_level < threshold_level:
            return False

        row = await connection.fetchrow(
            "SELECT metadata FROM sessions WHERE id = $1", session_id
        )
        if not row:
            return False

        metadata = row.get("metadata") or {}
        last_alert = metadata.get("last_alert_at")
        if not last_alert:
            return True

        try:
            last_dt = datetime.fromisoformat(last_alert.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            return True

        delta = datetime.now(timezone.utc) - last_dt
        return delta.total_seconds() >= cooldown_seconds

    @abstractmethod
    async def send_alert(self, alert: EmergencyAlert) -> bool:
        """Dispatch ``alert`` over the underlying transport.

        Returns:
            ``True`` if the alert was successfully handed off,
            ``False`` if the transport was configured-but-unreachable.

        Implementations should NOT raise on transport errors -- the
        caller treats ``False`` as "alert not sent, retry later".
        """

    async def send_assessment_summary(self, alert: EmergencyAlert) -> bool:
        """Notify staff that a triage assessment has been completed.

        Default implementation delegates to :meth:`send_alert` so
        legacy notifiers keep working. :class:`MockNotificationService`
        overrides with a distinct staff-facing format.
        """

        return await self.send_alert(alert)


class MockNotificationService(BaseNotificationService):
    """In-process notifier used by the demo and tests.

    Prints a clearly formatted block to stdout AND logs the same
    fields via the module logger. An operator running the API
    locally sees the dispatch immediately, and structured log
    sinks pick it up too. Always returns ``True`` because there's
    no external transport that can fail.
    """

    _DIVIDER = "=" * 64

    async def send_alert(self, alert: EmergencyAlert) -> bool:
        symptoms_str = (
            ", ".join(alert.detected_symptoms)
            if alert.detected_symptoms
            else "n/a"
        )
        confidence_str = (
            f"{alert.confidence:.2f}" if alert.confidence is not None else "n/a"
        )

        block = (
            "\n"
            f"{self._DIVIDER}\n"
            "  EMERGENCY ALERT (mock notifier)\n"
            f"{self._DIVIDER}\n"
            f"  Session ID    : {alert.session_id}\n"
            f"  Language      : {alert.language}\n"
            f"  Severity      : {alert.severity}\n"
            f"  Confidence    : {confidence_str}\n"
            f"  Department    : {alert.department_name or 'n/a'}\n"
            f"  Patient Name  : {alert.patient_name or 'n/a'}\n"
            f"  Phone Number  : {alert.phone_number or 'n/a'}\n"
            f"  Address       : {alert.address or 'n/a'}\n"
            f"  Symptoms      : {symptoms_str}\n"
            f"  Alert Message : {alert.alert_message or 'n/a'}\n"
            f"{self._DIVIDER}\n"
        )
        print(block, flush=True)

        logger.warning(
            "Emergency alert dispatched (mock) | session=%s severity=%s "
            "department=%s patient=%s phone=%s symptoms=%s alert_message=%s",
            alert.session_id,
            alert.severity,
            alert.department_name or "n/a",
            alert.patient_name or "n/a",
            alert.phone_number or "n/a",
            symptoms_str,
            alert.alert_message or "n/a",
        )
        return True

    async def send_assessment_summary(self, alert: EmergencyAlert) -> bool:
        """Notify staff of a completed triage assessment (any severity).

        Used when a voice or text session finishes and the patient has
        received their result. Distinct from :meth:`send_alert`, which is
        reserved for emergency dispatch with contact details.
        """

        symptoms_str = (
            ", ".join(alert.detected_symptoms)
            if alert.detected_symptoms
            else "n/a"
        )
        confidence_str = (
            f"{alert.confidence:.2f}" if alert.confidence is not None else "n/a"
        )

        block = (
            "\n"
            f"{self._DIVIDER}\n"
            "  TRIAGE ASSESSMENT SUMMARY (staff)\n"
            f"{self._DIVIDER}\n"
            f"  Session ID    : {alert.session_id}\n"
            f"  Language      : {alert.language}\n"
            f"  Severity      : {alert.severity}\n"
            f"  Confidence    : {confidence_str}\n"
            f"  Department    : {alert.department_name or 'n/a'}\n"
            f"  Patient Name  : {alert.patient_name or 'n/a'}\n"
            f"  Phone Number  : {alert.phone_number or 'n/a'}\n"
            f"  Address       : {alert.address or 'n/a'}\n"
            f"  Symptoms      : {symptoms_str}\n"
            f"  Summary       : {alert.alert_message or 'n/a'}\n"
            f"{self._DIVIDER}\n"
        )
        print(block, flush=True)

        logger.info(
            "Triage assessment summary sent to staff (mock) | session=%s "
            "severity=%s department=%s",
            alert.session_id,
            alert.severity,
            alert.department_name or "n/a",
        )
        return True
