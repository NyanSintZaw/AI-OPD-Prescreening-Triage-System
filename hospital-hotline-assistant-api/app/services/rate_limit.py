"""In-process per-IP rate limiting for the few endpoints that need it.

Login is brute-forceable and the HN endpoints turn a guessable hospital number
into patient identity, so both get a sliding-window cap per client IP.

ponytail: single-process only (one uvicorn worker per booth server) and keyed
on the socket peer, so a reverse proxy would collapse every client onto one
key — switch to a shared store / X-Forwarded-For parsing only if this API is
ever fronted by a proxy or run with more than one worker.
"""

from __future__ import annotations

import time
from collections import deque

from fastapi import HTTPException, Request

_hits: dict[str, deque[float]] = {}


def rate_limit(name: str, *, limit: int, window_seconds: float):
    """FastAPI dependency: at most ``limit`` calls per IP per window."""

    async def _check(request: Request) -> None:
        client = request.client.host if request.client else "unknown"
        key = f"{name}:{client}"
        now = time.monotonic()
        hits = _hits.setdefault(key, deque())
        while hits and now - hits[0] > window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            raise HTTPException(
                status_code=429,
                detail="Too many requests, please try again shortly",
                headers={"Retry-After": str(int(window_seconds - (now - hits[0])) + 1)},
            )
        hits.append(now)
        if len(_hits) > 1024:  # keep idle clients from accumulating forever
            for stale in [
                k for k, v in _hits.items() if not v or now - v[-1] > window_seconds
            ]:
                del _hits[stale]

    return _check
