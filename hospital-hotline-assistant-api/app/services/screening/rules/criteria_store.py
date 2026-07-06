"""Load and cache versioned screening criteria.

Criteria versions are immutable once written, so parsed documents are cached
by version id for the process lifetime. Sessions pin the version id they
started with, so a mid-conversation activation never mixes rule sets.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .criteria_models import ScreeningCriteria, parse_criteria

logger = logging.getLogger(__name__)

SEED_CRITERIA_PATH = Path(__file__).resolve().parents[3] / "data" / "screening_criteria_v1.json"

_cache: dict[str, ScreeningCriteria] = {}


def load_seed_criteria() -> ScreeningCriteria:
    """Parse the bundled hand-encoded criteria (also the DB-empty fallback)."""

    with open(SEED_CRITERIA_PATH, encoding="utf-8") as fh:
        return parse_criteria(json.load(fh))


def _parse_row(row: dict[str, Any]) -> tuple[str, ScreeningCriteria]:
    version_id = str(row["id"])
    cached = _cache.get(version_id)
    if cached is None:
        payload = row["criteria"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        cached = parse_criteria(payload)
        _cache[version_id] = cached
    return version_id, cached


async def get_active_criteria(conn) -> tuple[str | None, ScreeningCriteria]:
    """Return (version_id, criteria) for the active version.

    Falls back to the bundled seed (version_id None) when no active row
    exists so a fresh database still screens safely.
    """

    row = await conn.fetchrow(
        "SELECT id, criteria FROM screening_criteria_versions WHERE status = 'active'"
    )
    if row is None:
        logger.warning("No active screening criteria in DB; using bundled seed")
        return None, load_seed_criteria()
    return _parse_row(dict(row))


async def get_criteria_version(conn, version_id: str) -> ScreeningCriteria | None:
    cached = _cache.get(version_id)
    if cached is not None:
        return cached
    row = await conn.fetchrow(
        "SELECT id, criteria FROM screening_criteria_versions WHERE id = $1",
        version_id,
    )
    if row is None:
        return None
    return _parse_row(dict(row))[1]
