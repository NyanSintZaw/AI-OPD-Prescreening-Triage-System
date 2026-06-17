"""Compatibility facade for the refactored Gemini Live voice service."""

from app.services.ai.live_audio import (
    _DEBUG_AUDIO,
    _DEBUG_EVENTS,
    _INPUT_AUDIO_MIME_TYPE,
)
from app.services.ai.live_events import (
    _smart_append,
    _strip_meta_markers,
    agent_transcript_signals_dispatch,
    extract_response_payload,
    log_event_shape,
)
from app.services.ai.live_service import (
    AssessmentCallback,
    EmergencyCallback,
    LiveVoiceService,
    TranscriptCallback,
    _kickoff_prompt,
)

__all__ = [
    "AssessmentCallback",
    "EmergencyCallback",
    "LiveVoiceService",
    "TranscriptCallback",
    "_DEBUG_AUDIO",
    "_DEBUG_EVENTS",
    "_INPUT_AUDIO_MIME_TYPE",
    "_kickoff_prompt",
    "_smart_append",
    "_strip_meta_markers",
    "agent_transcript_signals_dispatch",
    "extract_response_payload",
    "log_event_shape",
]
