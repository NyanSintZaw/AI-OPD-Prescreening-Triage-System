"""Find an in-progress session linked to a hospital visit (VN).

Used by ``GET /sessions/by-visit/{visit_id}`` so the kiosk can resume after a
hang-up / walk-away instead of creating a fresh session for the same VN.
"""

from __future__ import annotations

import asyncpg

# Only sessions started within this window are resumable. A VN is a same-day
# hospital visit; without a cutoff, a booth run abandoned days ago would
# hijack the VN forever (live E2E finding, July 22: 3-day-old stale actives
# answered the by-visit lookup).
RESUME_WINDOW_HOURS = 12


async def find_active_session_by_visit_id(
    connection: asyncpg.Connection,
    visit_id: str,
    *,
    window_hours: int = RESUME_WINDOW_HOURS,
) -> asyncpg.Record | None:
    """Return the most recent same-day session linked to ``visit_id``, or None.

    Linkage lives in ``sessions.metadata->'visit'->>'visit_id'`` (set by
    ``POST /sessions/{id}/link-visit``). Returns ``active`` sessions (the
    kiosk offers continue-or-start-over) AND recently ``completed`` ones
    (the kiosk offers start-over / reprint slip). ``reset``/``escalated``
    are ignored, as is anything older than the resume window.
    """
    cleaned = (visit_id or "").strip()
    if not cleaned:
        return None
    return await connection.fetchrow(
        """
        SELECT *
        FROM sessions
        WHERE status IN ('active', 'completed')
          AND metadata->'visit'->>'visit_id' = $1
          AND started_at > NOW() - make_interval(hours => $2)
        ORDER BY started_at DESC
        LIMIT 1
        """,
        cleaned,
        window_hours,
    )
