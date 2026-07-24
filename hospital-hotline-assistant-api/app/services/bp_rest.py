"""BP 15-minute rest window after hypertensive-crisis readings.

Keyed by HN (preferred) or visit_id so the timer persists across intervening
kiosk patients / session hang-ups — matching the meeting requirement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import asyncpg

# Matches dv_adult_bp_crisis in screening_criteria_v1.json
CRISIS_SBP = 180
CRISIS_DBP = 110
REST_DURATION = timedelta(minutes=15)


def is_hypertensive_crisis(systolic: float | int | None, diastolic: float | int | None) -> bool:
    """True when the reading meets the MFU danger-vital BP crisis thresholds."""
    try:
        if systolic is not None and float(systolic) > CRISIS_SBP:
            return True
        if diastolic is not None and float(diastolic) > CRISIS_DBP:
            return True
    except (TypeError, ValueError):
        return False
    return False


def compute_rest_until(
    *,
    now: datetime | None = None,
    duration: timedelta = REST_DURATION,
) -> datetime:
    anchor = now or datetime.now(timezone.utc)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    return anchor + duration


@dataclass(frozen=True)
class BpRestStatus:
    resting: bool
    rest_until: datetime | None = None
    seconds_remaining: int = 0
    reason: str | None = None
    hn: str | None = None
    visit_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "resting": self.resting,
            "rest_until": self.rest_until.isoformat() if self.rest_until else None,
            "seconds_remaining": self.seconds_remaining,
            "reason": self.reason,
            "hn": self.hn,
            "visit_id": self.visit_id,
        }


async def get_active_rest(
    connection: asyncpg.Connection,
    *,
    hn: str | None = None,
    visit_id: str | None = None,
    now: datetime | None = None,
) -> BpRestStatus:
    """Return the active (unresolved, still in the future) rest window if any."""
    if not hn and not visit_id:
        return BpRestStatus(resting=False)

    anchor = now or datetime.now(timezone.utc)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)

    row = await connection.fetchrow(
        """
        SELECT hn, visit_id, rest_until, reason
        FROM bp_rest_windows
        WHERE resolved_at IS NULL
          AND rest_until > $1
          AND (
                ($2::text IS NOT NULL AND hn = $2)
             OR ($3::text IS NOT NULL AND visit_id = $3)
          )
        ORDER BY rest_until DESC
        LIMIT 1
        """,
        anchor,
        hn,
        visit_id,
    )
    if row is None:
        return BpRestStatus(resting=False)

    rest_until = row["rest_until"]
    if rest_until.tzinfo is None:
        rest_until = rest_until.replace(tzinfo=timezone.utc)
    remaining = max(0, int((rest_until - anchor).total_seconds()))
    return BpRestStatus(
        resting=remaining > 0,
        rest_until=rest_until,
        seconds_remaining=remaining,
        reason=row["reason"],
        hn=row["hn"],
        visit_id=row["visit_id"],
    )


async def has_prior_window(
    connection: asyncpg.Connection,
    *,
    hn: str | None = None,
    visit_id: str | None = None,
    within_hours: int = 24,
) -> bool:
    """True when this patient/visit already had a rest window recently.

    The meeting flow is rest ONCE then proceed: the first crisis reading
    opens the window; the post-rest reading is confirmatory and must reach
    the rules engine even if still critical — never loop the patient
    through endless 15-minute rests.
    """
    if not hn and not visit_id:
        return False
    row = await connection.fetchrow(
        """
        SELECT 1 FROM bp_rest_windows
        WHERE created_at > NOW() - make_interval(hours => $3)
          AND (
                ($1::text IS NOT NULL AND hn = $1)
             OR ($2::text IS NOT NULL AND visit_id = $2)
          )
        LIMIT 1
        """,
        hn,
        visit_id,
        within_hours,
    )
    return row is not None


async def resolve_windows_for(
    connection: asyncpg.Connection,
    *,
    hn: str | None = None,
    visit_id: str | None = None,
    now: datetime | None = None,
) -> None:
    """Mark this patient's open windows resolved (the recheck happened)."""
    if not hn and not visit_id:
        return
    anchor = now or datetime.now(timezone.utc)
    await connection.execute(
        """
        UPDATE bp_rest_windows
        SET resolved_at = $3
        WHERE resolved_at IS NULL
          AND (
                ($1::text IS NOT NULL AND hn = $1)
             OR ($2::text IS NOT NULL AND visit_id = $2)
          )
        """,
        hn,
        visit_id,
        anchor,
    )


async def open_rest_window(
    connection: asyncpg.Connection,
    *,
    hn: str | None,
    visit_id: str | None,
    reading_id: UUID | None = None,
    reason: str = "hypertensive_crisis",
    now: datetime | None = None,
) -> datetime:
    """Insert a new rest window. Callers should only invoke this on crisis BP."""
    if not hn and not visit_id:
        raise ValueError("hn or visit_id required to open a BP rest window")
    rest_until = compute_rest_until(now=now)
    await connection.execute(
        """
        INSERT INTO bp_rest_windows
            (hn, visit_id, triggered_by_reading, rest_until, reason)
        VALUES ($1, $2, $3, $4, $5)
        """,
        hn,
        visit_id,
        reading_id,
        rest_until,
        reason,
    )
    return rest_until


async def resolve_expired_windows(
    connection: asyncpg.Connection,
    *,
    now: datetime | None = None,
) -> int:
    """Mark past-due windows resolved (housekeeping; optional)."""
    anchor = now or datetime.now(timezone.utc)
    result = await connection.execute(
        """
        UPDATE bp_rest_windows
        SET resolved_at = $1
        WHERE resolved_at IS NULL AND rest_until <= $1
        """,
        anchor,
    )
    # asyncpg returns e.g. "UPDATE 2"
    try:
        return int(str(result).split()[-1])
    except (ValueError, IndexError):
        return 0
