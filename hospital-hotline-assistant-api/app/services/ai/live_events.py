"""Event and transcript helpers for text and live ADK streams."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_META_PREFIX_TOKEN_RE = re.compile(
    r"^\s*\[\s*(?:MODE|LANG|CALL_START|SYSTEM_ACTION)\b[^\]]*\]\s*",
    re.IGNORECASE,
)


def _strip_meta_markers(reply: str) -> str:
    """Remove leading model-echoed mode/language markers."""

    if not reply:
        return reply
    while True:
        stripped = _META_PREFIX_TOKEN_RE.sub("", reply, count=1)
        if stripped == reply:
            break
        reply = stripped
    return reply.lstrip()


def _collapse_adjacent_repeat(text: str) -> str:
    """Collapse a fragment that is the same phrase emitted twice."""

    words = text.split()
    if len(words) < 2 or len(words) % 2:
        return text
    midpoint = len(words) // 2
    if words[:midpoint] == words[midpoint:]:
        return " ".join(words[:midpoint])
    return text


def _smart_append(chunks: list[str], fragment: str) -> str | None:
    """Append transcript fragments while suppressing duplicate/snapshot output."""

    f = _collapse_adjacent_repeat(fragment.strip())
    if not f:
        return None
    existing = " ".join(c.strip() for c in chunks if c.strip()).strip()
    if not existing:
        chunks.append(f)
        return f
    if existing.endswith(f):
        return None
    if f.startswith(existing):
        delta = f[len(existing):].strip()
        chunks.clear()
        chunks.append(f)
        return delta or None
    chunks.append(f)
    return f


def log_event_shape(session_id: str, event: Any) -> None:
    """Dump a one-line summary of a live ADK event's useful attributes."""

    try:
        content = getattr(event, "content", None)
        parts = getattr(content, "parts", None) or []
        part_kinds: list[str] = []
        for p in parts:
            kinds = []
            if getattr(p, "inline_data", None) is not None:
                kinds.append("audio")
            if getattr(p, "text", None):
                kinds.append("text")
            if getattr(p, "function_call", None) is not None:
                kinds.append("fn_call")
            if getattr(p, "function_response", None) is not None:
                kinds.append("fn_resp")
            part_kinds.append("+".join(kinds) if kinds else "empty")
        calls = (
            event.get_function_calls()
            if callable(getattr(event, "get_function_calls", None))
            else []
        )
        responses = (
            event.get_function_responses()
            if callable(getattr(event, "get_function_responses", None))
            else []
        )
        logger.info(
            "[LIVE_DEBUG %s] author=%s partial=%s final=%s "
            "parts=%s calls=%d resps=%d in_tx=%s out_tx=%s",
            session_id,
            getattr(event, "author", "?"),
            getattr(event, "partial", None),
            callable(getattr(event, "is_final_response", None))
            and event.is_final_response(),
            part_kinds,
            len(calls),
            len(responses),
            bool(getattr(event, "input_transcription", None)),
            bool(getattr(event, "output_transcription", None)),
        )
        if responses:
            for r in responses:
                logger.info(
                    "[LIVE_DEBUG %s] fn_resp name=%s response=%r",
                    session_id,
                    getattr(r, "name", "?"),
                    getattr(r, "response", None),
                )
    except Exception:
        logger.exception("Debug event dump failed for %s", session_id)


def extract_response_payload(func_response: Any) -> dict[str, Any] | None:
    """Coerce an ADK FunctionResponse into the plain dict our tools return."""

    if func_response is None:
        return None
    response = getattr(func_response, "response", None)
    if isinstance(response, dict):
        return response
    out = getattr(func_response, "output", None)
    if isinstance(out, dict):
        return out
    return None
