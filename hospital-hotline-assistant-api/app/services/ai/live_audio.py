"""Live voice audio constants and debug flags."""

from __future__ import annotations

import os

_DEBUG_EVENTS: bool = os.environ.get("LIVE_DEBUG_EVENTS", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

_DEBUG_AUDIO: bool = os.environ.get("LIVE_DEBUG_AUDIO", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

_INPUT_AUDIO_MIME_TYPE: str = "audio/pcm;rate=16000"
