"""State stores: screening_sessions persistence + in-memory fallback."""

from __future__ import annotations

import json
import logging
from typing import Protocol

from .rules.criteria_models import ScreeningCriteria
from .rules.criteria_store import get_active_criteria, get_criteria_version, load_seed_criteria
from .state import ScreeningState

logger = logging.getLogger(__name__)


class StateStore(Protocol):
    async def load(self, session_id: str) -> ScreeningState | None: ...

    async def save(self, state: ScreeningState) -> None: ...

    async def get_criteria(
        self, pinned_version_id: str | None
    ) -> tuple[str | None, ScreeningCriteria]:
        """Return (version_id, criteria) — the pinned version when given,
        otherwise the active one."""
        ...

    async def write_audit(
        self,
        *,
        session_id: str,
        turn_no: int,
        entries: list[dict],
        model_name: str,
        prompt_version: str,
        criteria_version_id: str | None,
    ) -> None:
        """Persist per-call audit entries for one turn (SRS traceability)."""
        ...


class InMemoryStateStore:
    """Dev/test store: process-local state, bundled seed criteria."""

    def __init__(self, criteria: ScreeningCriteria | None = None) -> None:
        self._states: dict[str, ScreeningState] = {}
        self._criteria = criteria or load_seed_criteria()

    async def load(self, session_id: str) -> ScreeningState | None:
        state = self._states.get(session_id)
        return ScreeningState.from_json(state.to_json()) if state else None

    async def save(self, state: ScreeningState) -> None:
        self._states[state.session_id] = ScreeningState.from_json(state.to_json())

    async def get_criteria(
        self, pinned_version_id: str | None
    ) -> tuple[str | None, ScreeningCriteria]:
        return pinned_version_id, self._criteria

    async def write_audit(self, **kwargs) -> None:
        self.audit_log = getattr(self, "audit_log", [])
        self.audit_log.append(kwargs)


class PostgresStateStore:
    """screening_sessions-backed store on the app's asyncpg pool."""

    def __init__(self, pool) -> None:
        self._pool = pool

    async def load(self, session_id: str) -> ScreeningState | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT state FROM screening_sessions WHERE session_id = $1",
                session_id,
            )
        if row is None:
            return None
        payload = row["state"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return ScreeningState.from_json(payload)

    async def save(self, state: ScreeningState) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO screening_sessions
                    (session_id, state, criteria_version_id, prompt_version, updated_at)
                VALUES ($1, $2::jsonb, $3, $4, NOW())
                ON CONFLICT (session_id) DO UPDATE SET
                    state = EXCLUDED.state,
                    criteria_version_id = EXCLUDED.criteria_version_id,
                    prompt_version = EXCLUDED.prompt_version,
                    updated_at = NOW()
                """,
                state.session_id,
                state.to_json(),
                state.criteria_version_id,
                state.prompt_version,
            )

    async def get_criteria(
        self, pinned_version_id: str | None
    ) -> tuple[str | None, ScreeningCriteria]:
        async with self._pool.acquire() as conn:
            if pinned_version_id:
                pinned = await get_criteria_version(conn, pinned_version_id)
                if pinned is not None:
                    return pinned_version_id, pinned
                logger.warning(
                    "Pinned criteria version %s missing; falling back to active",
                    pinned_version_id,
                )
            return await get_active_criteria(conn)

    async def write_audit(
        self,
        *,
        session_id: str,
        turn_no: int,
        entries: list[dict],
        model_name: str,
        prompt_version: str,
        criteria_version_id: str | None,
    ) -> None:
        if not entries:
            return
        rows = []
        for entry in entries:
            payload = dict(entry)
            call_site = str(payload.pop("call_site", "unknown"))
            ok = bool(payload.pop("ok", True))
            latency_ms = payload.pop("latency_ms", None)
            violations = payload.pop("violations", None)
            rows.append((
                session_id, turn_no, call_site, model_name, prompt_version,
                criteria_version_id,
                json.dumps(payload, ensure_ascii=False) if payload else None,
                json.dumps(violations, ensure_ascii=False) if violations else None,
                ok,
                int(latency_ms) if latency_ms is not None else None,
            ))
        try:
            async with self._pool.acquire() as conn:
                await conn.executemany(
                    """
                    INSERT INTO ai_inference_audit (
                        session_id, turn_no, call_site, model_name, prompt_version,
                        criteria_version_id, rules_trace, validator_result, ok, latency_ms
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, $10)
                    """,
                    rows,
                )
        except Exception:
            # Audit must never break a patient turn.
            logger.exception("failed to write ai_inference_audit rows")
