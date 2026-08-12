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

SEED_CRITERIA_PATH = Path(__file__).resolve().parents[3] / "data" / "screening_criteria.json"

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


# --- version review helpers (used by the /admin/criteria/* lifecycle) --------

def validation_errors(payload: dict[str, Any]) -> list[str]:
    """Human-readable schema errors for a criteria payload ([] when valid)."""
    from pydantic import ValidationError

    try:
        parse_criteria(payload)
        return []
    except ValidationError as exc:
        return [
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in exc.errors()[:50]
        ]
    except Exception as exc:  # noqa: BLE001
        return [str(exc)]


def diff_criteria(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Field-level diff between two criteria payloads, keyed by rule ids."""

    sections = [
        ("level1_criteria", "id"), ("danger_vitals", "id"),
        ("department_rules", "id"), ("fast_tracks", "id"),
        ("triage_tuples", "id"), ("routing_table", "complaint_category"),
        ("complaint_templates", "category"),
    ]
    result: dict[str, Any] = {}
    for section, key in sections:
        old_items = {item.get(key): item for item in old.get(section, [])}
        new_items = {item.get(key): item for item in new.get(section, [])}
        added = sorted(k for k in new_items if k not in old_items)
        removed = sorted(k for k in old_items if k not in new_items)
        changed = sorted(
            k for k in new_items
            if k in old_items and new_items[k] != old_items[k]
        )
        if added or removed or changed:
            result[section] = {"added": added, "removed": removed, "changed": changed}

    # Sections stored as a mapping rather than a list of rules.
    for section in ("finding_catalog", "vital_bounds", "cross_checks"):
        old_map = old.get(section, {})
        new_map = new.get(section, {})
        added = sorted(k for k in new_map if k not in old_map)
        removed = sorted(k for k in old_map if k not in new_map)
        changed = sorted(
            k for k in new_map if k in old_map and new_map[k] != old_map[k]
        )
        if added or removed or changed:
            result[section] = {"added": added, "removed": removed, "changed": changed}
    return result
