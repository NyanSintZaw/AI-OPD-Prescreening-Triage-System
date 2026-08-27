"""Startup self-check for the three AI legs (LLM, STT, TTS).

Every leg in this app is a config seam, which is exactly why a
misconfiguration is so quiet: a wrong ``*_BASE_URL`` or an unreachable
sidecar does not fail at boot, it fails on the first patient turn — as a
404 buried in a traceback, or worse, as a silent fall-back to a canned
template while the kiosk looks fine.

So we ask each leg one real question at startup and print the answers as a
banner. Not a ping: the LLM gets a completion, the TTS a synthesis, and the
STT transcribes the TTS's own audio, so a PASS means the leg actually did
its job end to end. Best-effort and non-blocking — this reports, it never
stops the app from serving.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
import wave
from typing import Any

from app.services.log_target import operational_logger

logger = logging.getLogger(__name__)


def _banner_logger() -> logging.Logger:
    return operational_logger(logger)


_WIDTH = 60
_PROBE_TH = "ทดสอบระบบเสียง"  # "voice system test" — short, cheap to synthesise
_PROBE_LLM = "Reply with exactly: OK"


class _Leg:
    """One leg's result, formatted for the banner."""

    def __init__(self, name: str, provider: str, target: str, detail: str):
        self.name = name
        self.provider = provider
        self.target = target
        self.detail = detail
        self.ok = False
        self.seconds = 0.0
        self.note = ""
        self.error = ""

    def lines(self) -> list[str]:
        mark = "OK  " if self.ok else "FAIL"
        head = f"  {self.name:4s} {mark} {self.seconds:6.2f}s  {self.provider}  {self.detail}"
        out = [head, f"            {self.target}"]
        if self.ok and self.note:
            out.append(f"            {self.note}")
        if not self.ok:
            out.append(f"            {self.error}")
        return out


def _wrap_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Re-wrap headerless linear16 PCM as a WAV file for the STT leg."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _root_cause(exc: BaseException) -> BaseException:
    """Follow ``raise ... from`` down to the exception that actually explains it.

    The speech adapter re-raises as ``RuntimeError(f"Local TTS error: {exc}")``,
    and httpx's ReadTimeout stringifies to "" — so the surface error reads
    "Local TTS error: " with nothing after the colon, which says nothing. The
    cause underneath is the ReadTimeout we want to name.
    """
    seen = {id(exc)}
    root = exc
    while (cause := root.__cause__) is not None and id(cause) not in seen:
        seen.add(id(cause))
        root = cause
    return root


def _describe(exc: BaseException, budget: float, setting: str) -> str:
    """Turn an exception into the one line an operator can act on."""
    root = _root_cause(exc)
    name = type(root).__name__
    # One line only: httpx appends a "For more information check: <mdn url>"
    # paragraph that would wrap the banner into unreadability.
    text = str(root).strip().splitlines()[0].strip() if str(root).strip() else ""
    if isinstance(root, (asyncio.TimeoutError, TimeoutError)) or "Timeout" in name:
        return (
            f"{name}: no response within {budget:.0f}s — "
            f"the sidecar is down or slower than {setting}"
        )
    if "404" in text or "Not Found" in text:
        return f"{name}: {text[:120]} — check the base URL ends in /v1"
    if not text:
        return f"{name}: connection closed without a response"
    return f"{name}: {text[:200]}"


async def _check_llm(settings: Any) -> _Leg:
    provider = settings.screening_model_provider
    target = settings.screening_openai_base_url or "(provider default)"
    if provider != "openai_compatible":
        target = f"{settings.google_cloud_project}/{settings.google_cloud_location}"
    leg = _Leg("LLM", provider, target, settings.screening_model_name)
    budget = float(settings.screening_model_timeout_s)

    started = time.perf_counter()
    try:
        from app.services.screening.model_adapter import build_chat_model

        model = build_chat_model(settings)
        reply = await asyncio.wait_for(model.ainvoke(_PROBE_LLM), timeout=budget)
        text = (getattr(reply, "content", "") or "").strip()
        if not text:
            raise RuntimeError("model returned an empty completion")
        leg.ok = True
        leg.note = f'answered {text[:40]!r}'
    except Exception as exc:  # noqa: BLE001 — every failure is reportable
        leg.error = _describe(exc, budget, "SCREENING_MODEL_TIMEOUT_S")
    leg.seconds = time.perf_counter() - started
    return leg


def _speech_labels(settings: Any, leg: str) -> tuple[str, str]:
    """(target, detail) for one speech leg, per provider."""
    if leg == "STT":
        provider = settings.stt_provider
        if provider == "local":
            return "in-process", settings.stt_local_model
        if provider == "google":
            return "(Google Cloud STT)", "default"
        return settings.stt_base_url or "(unset)", settings.stt_model
    provider = settings.tts_provider
    if provider == "local":
        return "in-process", f"F5-TTS-THAI/{settings.tts_local_model}"
    if provider == "google":
        return "(Google Cloud TTS)", settings.tts_voice_th
    return settings.tts_base_url or "(unset)", settings.tts_model


async def _prewarm(client: Any, leg: str) -> None:
    """Load an in-process model before timing it.

    Loading is a one-off cost measured in minutes (F5 took 69 s here, whisper
    58 s on first download) and has nothing to do with whether the leg works.
    Timing it against the per-call speech budget just reports a false FAIL.
    """
    prewarm = getattr(client, "prewarm", None)
    if prewarm is None:
        return
    started = time.perf_counter()
    _banner_logger().info("Loading in-process %s model…", leg)
    await prewarm()
    _banner_logger().info(
        "In-process %s model ready in %.1fs", leg, time.perf_counter() - started
    )


async def _check_tts(settings: Any, tts_client: Any) -> tuple[_Leg, bytes]:
    provider = settings.tts_provider
    target, detail = _speech_labels(settings, "TTS")
    leg = _Leg("TTS", provider, target, detail)
    budget = float(settings.speech_http_timeout_s)

    audio = b""
    started = time.perf_counter()
    try:
        if provider == "local":
            await _prewarm(tts_client, "TTS")
            started = time.perf_counter()  # time synthesis, not the load
        audio = await asyncio.wait_for(
            tts_client.synthesize(
                text=_PROBE_TH, language="th",
                audio_encoding="linear16", sample_rate_hertz=24000,
            ),
            timeout=budget + 5,
        )
        if not audio:
            raise RuntimeError("synthesis returned no audio")
        leg.ok = True
        leg.note = f"{len(audio)} bytes of 24 kHz PCM ({len(audio) / 48000:.1f}s)"
    except Exception as exc:  # noqa: BLE001
        leg.error = _describe(exc, budget, "SPEECH_HTTP_TIMEOUT_S")
    leg.seconds = time.perf_counter() - started
    return leg, audio


async def _check_stt(settings: Any, stt_client: Any, tts_audio: bytes) -> _Leg:
    provider = settings.stt_provider
    target, detail = _speech_labels(settings, "STT")
    leg = _Leg("STT", provider, target, detail)
    budget = float(settings.speech_http_timeout_s)

    # Normally we transcribe the TTS leg's own speech, which proves STT end to
    # end. When TTS is down there is no speech to send — but "STT untested" is
    # a much worse answer than "STT is reachable", so fall back to a second of
    # silence and report reachability only. Silence legitimately transcribes to
    # "", so an empty result is not a failure in that mode.
    speech = bool(tts_audio)
    audio = tts_audio if speech else b"\x00\x00" * 24000

    started = time.perf_counter()
    try:
        if provider == "local":
            await _prewarm(stt_client, "STT")
            started = time.perf_counter()
        result = await asyncio.wait_for(
            stt_client.transcribe(
                audio_bytes=_wrap_wav(audio, 24000),
                language="th",
                mime_type="audio/wav",
            ),
            timeout=budget + 5,
        )
        transcript = (getattr(result, "transcript", "") or "").strip()
        if speech:
            if not transcript:
                raise RuntimeError("transcribed the probe speech as an empty string")
            leg.ok = True
            leg.note = f"heard {transcript[:40]!r} (spoke {_PROBE_TH!r})"
        else:
            leg.ok = True
            leg.note = "endpoint reachable — not verified against speech (TTS is down)"
    except Exception as exc:  # noqa: BLE001
        leg.error = _describe(exc, budget, "SPEECH_HTTP_TIMEOUT_S")
    leg.seconds = time.perf_counter() - started
    return leg


async def run_ai_selfcheck(settings: Any, *, stt_client: Any, tts_client: Any) -> bool:
    """Probe all three legs and log the banner. Returns True iff all passed.

    STT runs on the TTS leg's own output, so the two are checked in order —
    the LLM runs alongside them since it shares nothing with either.
    """
    llm_task = asyncio.create_task(_check_llm(settings))
    tts_leg, audio = await _check_tts(settings, tts_client)
    stt_leg = await _check_stt(settings, stt_client, audio)
    llm_leg = await llm_task

    legs = [llm_leg, stt_leg, tts_leg]
    failed = [leg for leg in legs if not leg.ok]

    rule = "=" * _WIDTH
    body = [
        rule,
        f"AI STACK SELF-CHECK   mode={settings.ai_mode}"
        f"   {'ALL OK' if not failed else str(len(failed)) + ' FAILING'}",
        "-" * _WIDTH,
    ]
    for leg in legs:
        body.extend(leg.lines())
    body.append(rule)
    message = "\n".join(body)

    out = _banner_logger()
    if failed:
        out.error("%s", message)
        out.error(
            "Patients will hear canned fallback text for: %s. "
            "The kiosk still serves — check the URLs above and the sidecar.",
            ", ".join(leg.name for leg in failed),
        )
    else:
        out.info("%s", message)
    return not failed


def start_ai_selfcheck(settings: Any, *, stt_client: Any, tts_client: Any) -> asyncio.Task:
    """Fire the self-check in the background so startup is never blocked."""

    async def _runner() -> None:
        try:
            await run_ai_selfcheck(settings, stt_client=stt_client, tts_client=tts_client)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a broken check must not break boot
            # Same logger as the banner: this module's own logger has no
            # handler under uvicorn, so reporting there would be silent.
            _banner_logger().exception("AI stack self-check could not run")

    return asyncio.create_task(_runner())
