"""Per-turn tracing for a voice call: what the mic sent, and where it went.

A voice turn fans out to three separate services, and when one of them fails
the patient just hears a canned apology — the log shows a traceback (or, if
the leg fell back, nothing at all) with no indication of which URL was being
called or how far the turn got. That is a bad place to debug from when the
AI node is a box on the other end of a tunnel.

So every turn narrates itself as a flat, greppable sequence:

    [voice 7c77aab3 t1] mic 4.2s (134400 B @16kHz, ended by tap)
    [voice 7c77aab3 t1] -> STT  https://host/v1/audio/transcriptions  (large-v3-turbo)
    [voice 7c77aab3 t1] <- STT  ok 1.42s  'ผมปวดหัวและมีไข้'
    [voice 7c77aab3 t1] -> LLM  https://host/v1  (scb10x/llama3.1-typhoon2-8b-instruct)
    [voice 7c77aab3 t1] <- LLM  ok 5.51s  reply 'ปวดหัวมานานแค่ไหนคะ'
    [voice 7c77aab3 t1] -> TTS  https://host/v1/audio/speech  (mms-tts, th)
    [voice 7c77aab3 t1] <- TTS  ok 2.13s  64000 B
    [voice 7c77aab3 t1] turn complete in 9.06s

``grep 'voice 7c77aab3'`` replays one call; ``grep -- '<- STT'`` audits one
leg across every call. The arrows are the point: a turn that stops after a
``->`` line names the exact URL that swallowed it.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.log_target import operational_logger

_module_logger = logging.getLogger(__name__)


def _log() -> logging.Logger:
    """Resolved per call: uvicorn installs its handlers after import."""
    return operational_logger(_module_logger)


def _short(session_id: str) -> str:
    """First block of the session UUID — enough to group a call in a log."""
    return str(session_id).split("-")[0]


def tag(session_id: str, turn: int) -> str:
    return f"[voice {_short(session_id)} t{turn}]"


def leg_targets(settings: Any) -> dict[str, str]:
    """Where each leg will actually send its request.

    Read from settings at call time rather than cached, because the admin
    surfaces can swap providers while the app is running.
    """
    def speech(provider: str, base_url: str | None, path: str, cloud: str) -> str:
        # "local" has no URL at all — the model is in this process, and saying
        # "(Google Cloud TTS)" there is worse than saying nothing.
        if provider == "local":
            return "in-process"
        if base_url:
            return f"{base_url.rstrip('/')}{path}"
        return cloud

    return {
        "STT": speech(
            settings.stt_provider, settings.stt_base_url,
            "/audio/transcriptions", "(Google Cloud STT)",
        ),
        "TTS": speech(
            settings.tts_provider, settings.tts_base_url,
            "/audio/speech", "(Google Cloud TTS)",
        ),
        "LLM": settings.screening_openai_base_url or "(Vertex AI)",
    }


def mic(session_id: str, turn: int, pcm_bytes: int, sample_rate: int, trigger: str) -> None:
    seconds = pcm_bytes / (sample_rate * 2)
    _log().info(
        "%s mic %.1fs (%d B @%dkHz, ended by %s)",
        tag(session_id, turn), seconds, pcm_bytes, sample_rate // 1000, trigger,
    )


def sending(session_id: str, turn: int, leg: str, target: str, detail: str) -> None:
    _log().info("%s -> %-3s %s  (%s)", tag(session_id, turn), leg, target, detail)


def received(
    session_id: str, turn: int, leg: str, seconds: float, summary: str
) -> None:
    _log().info("%s <- %-3s ok %.2fs  %s", tag(session_id, turn), leg, seconds, summary)


def failed(
    session_id: str, turn: int, leg: str, seconds: float, target: str, exc: BaseException
) -> None:
    """Name the leg, the URL and the root cause on ONE line.

    The adapters wrap errors as ``RuntimeError("Local STT error: {exc}")`` and
    httpx timeouts stringify to "", so the surface message is often empty —
    follow ``__cause__`` to whatever actually went wrong.
    """
    root: BaseException = exc
    seen = {id(exc)}
    while (cause := root.__cause__) is not None and id(cause) not in seen:
        seen.add(id(cause))
        root = cause
    text = str(root).strip().splitlines()[0] if str(root).strip() else "no response"
    _log().error(
        "%s <- %-3s FAILED after %.2fs  %s  %s: %s",
        tag(session_id, turn), leg, seconds, target, type(root).__name__, text[:160],
    )


def complete(session_id: str, turn: int, seconds: float) -> None:
    _log().info("%s turn complete in %.2fs", tag(session_id, turn), seconds)
