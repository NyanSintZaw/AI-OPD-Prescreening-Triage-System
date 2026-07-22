"""Shared VN name-confirmation decision logic.

Used by both the REST endpoint (kiosk button/typed fallback) and the voice
bridge's spoken identity gate, so a "yes" always stamps
``metadata.visit.name_confirmed`` and a "no" always unlinks the visit the
same way, regardless of which channel the answer arrived on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from uuid import UUID

import asyncpg


class NoVisitLinkedError(Exception):
    """The session has no linked visit to confirm."""


@dataclass(frozen=True)
class ConfirmOutcome:
    decision: str  # "yes" | "no" | "uncertain" | "other"
    name_confirmed: bool
    unlinked: bool
    patient_name: str | None


def strip_his_prefill(metadata: dict) -> None:
    """Drop HIS-derived artifacts from session metadata in place.

    Called whenever a visit link is removed or replaced: the previous
    patient's HN history and HIS-seeded vitals (source ``his``/``his_recent``)
    must never carry over to an anonymous continue or a different patient
    (live E2E finding, July 22: rejected VN left the wrong patient's
    weight/height on the session). Cuff/manual readings (source ``device``/
    ``manual``) are real measurements of the person standing there — kept.
    """
    metadata.pop("patient_history", None)
    vitals = metadata.get("vitals") or {}
    if str(vitals.get("source") or "").startswith("his"):
        metadata.pop("vitals", None)


def needs_history_intake(metadata: Mapping[str, Any] | None) -> bool:
    """First-time patient whose booth history intake hasn't happened yet."""
    history = (metadata or {}).get("patient_history") or {}
    return bool(history.get("is_first_time")) and not bool(
        history.get("intake_complete")
    )


async def apply_confirm_decision(
    connection: asyncpg.Connection,
    session_id: UUID | str,
    decision: str,
) -> ConfirmOutcome:
    """Apply a yes/no/uncertain identity decision to the session.

    yes → ``metadata.visit.name_confirmed = True``; no → drop
    ``metadata.visit`` entirely (the kiosk re-prompts for a VN);
    uncertain/other → no change, caller re-asks.
    Raises ``NoVisitLinkedError`` when no visit is linked and ``ValueError``
    when the session doesn't exist.
    """
    session_row = await connection.fetchrow(
        "SELECT metadata FROM sessions WHERE id = $1", session_id
    )
    if session_row is None:
        raise ValueError("Session not found")

    metadata = dict(session_row["metadata"] or {})
    visit = dict(metadata.get("visit") or {})
    if not visit.get("visit_id"):
        raise NoVisitLinkedError

    raw_name = visit.get("patient_name")
    patient_name = raw_name if isinstance(raw_name, str) else None

    if decision == "yes":
        visit["name_confirmed"] = True
        metadata["visit"] = visit
        await connection.execute(
            "UPDATE sessions SET metadata = $2::jsonb WHERE id = $1",
            session_id,
            metadata,
        )
        return ConfirmOutcome("yes", True, False, patient_name)

    if decision == "no":
        metadata.pop("visit", None)
        strip_his_prefill(metadata)
        await connection.execute(
            "UPDATE sessions SET metadata = $2::jsonb WHERE id = $1",
            session_id,
            metadata,
        )
        return ConfirmOutcome("no", False, True, patient_name)

    # uncertain / other — leave the link untouched; caller re-prompts.
    return ConfirmOutcome(decision, False, False, patient_name)
