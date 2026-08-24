"""Find an in-progress session linked to a patient (HN).

Used by ``GET /sessions/by-hn/{hn}`` so the kiosk can resume after a
hang-up / walk-away instead of creating a fresh session for the same
patient. Many sessions may exist per HN — this returns only the most
recent one inside the resume window.
"""

from __future__ import annotations

import asyncpg

# Only sessions started within this window are resumable. An HN is a lifelong
# identity (not a same-day visit), so the cutoff matters even more than it
# did for VNs: without it, any prior booth run — even weeks old — would
# hijack the HN forever (live E2E finding, July 22: 3-day-old stale actives
# answered the lookup).
RESUME_WINDOW_HOURS = 12


async def find_active_session_by_hn(
    connection: asyncpg.Connection,
    hn: str,
    *,
    window_hours: int = RESUME_WINDOW_HOURS,
) -> asyncpg.Record | None:
    """Return the most recent recent-window session linked to ``hn``, or None.

    Linkage lives in ``sessions.metadata->'patient'->>'hn'`` (set by
    ``POST /sessions/{id}/link-patient``). Returns ``active`` sessions (the
    kiosk offers continue-or-start-over) AND recently ``completed`` ones
    (the kiosk offers start-over / reprint slip). ``reset``/``escalated``
    are ignored, as is anything older than the resume window.
    """
    cleaned = (hn or "").strip()
    if not cleaned:
        return None
    return await connection.fetchrow(
        """
        SELECT *
        FROM sessions
        WHERE status IN ('active', 'completed')
          AND metadata->'patient'->>'hn' = $1
          AND started_at > NOW() - make_interval(hours => $2)
        ORDER BY started_at DESC
        LIMIT 1
        """,
        cleaned,
        window_hours,
    )
