"""Shared first-time patient history persistence.

Used by both the REST endpoint (kiosk form fallback) and the voice bridge's
spoken history gate, so intake answers land in ``metadata.patient_history``
and the HIS HN the same way regardless of which channel collected them.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)

HISTORY_FIELDS = (
    "smoking_alcohol",
    "allergies",
    "chronic_conditions",
    "past_surgeries",
    "family_history",
)


async def store_patient_history(
    connection: asyncpg.Connection,
    session_id: UUID | str,
    payload: Mapping[str, Any],
    *,
    his_adapter: Any | None = None,
) -> dict[str, Any]:
    """Persist intake history to session metadata and (best-effort) the HIS HN.

    Marks the intake complete (``is_first_time=False``,
    ``intake_complete=True``) so ``needs_history_intake`` stops asking.
    Raises ``ValueError`` when the session doesn't exist.
    """
    session_row = await connection.fetchrow(
        "SELECT metadata FROM sessions WHERE id = $1", session_id
    )
    if session_row is None:
        raise ValueError("Session not found")

    metadata = dict(session_row["metadata"] or {})
    visit = dict(metadata.get("visit") or {})
    hn = visit.get("hn") if isinstance(visit.get("hn"), str) else None

    # Drop empty strings so HIS "none" semantics stay clean.
    history_payload = {
        k: (v.strip() if isinstance(v, str) else v)
        for k, v in ((field, payload.get(field)) for field in HISTORY_FIELDS)
        if v is not None and str(v).strip()
    }

    existing = dict(metadata.get("patient_history") or {})
    existing.update(history_payload)
    existing["is_first_time"] = False
    existing["intake_complete"] = True
    existing["recorded_at"] = datetime.now(timezone.utc).isoformat()
    metadata["patient_history"] = existing
    await connection.execute(
        "UPDATE sessions SET metadata = $2::jsonb WHERE id = $1",
        session_id,
        metadata,
    )

    pushed = False
    if hn and his_adapter is not None:
        try:
            pushed = bool(await his_adapter.push_patient_history(hn, history_payload))
        except Exception:  # noqa: BLE001 — booth must continue even if HIS is down
            logger.exception("Failed to push patient history to HIS hn=%s", hn)

    return {"saved": True, "pushed_to_his": pushed, "hn": hn}
