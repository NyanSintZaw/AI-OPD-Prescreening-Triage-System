"""Gemini Live ADK run configuration."""

from __future__ import annotations

from typing import Any

from app.services.ai.env import configure_google_genai_environment

configure_google_genai_environment()

from google.genai import types as genai_types  # noqa: E402

_VOICE_NAME: str = "Aoede"

_LANGUAGE_CODE_BY_LANG: dict[str, str] = {
    "en": "en-US",
    "th": "th-TH",
}


def build_live_run_config(language: str) -> Any:
    """Assemble the RunConfig ADK passes into Gemini Live."""

    from google.adk.runners import RunConfig

    bcp47 = _LANGUAGE_CODE_BY_LANG.get(language, _LANGUAGE_CODE_BY_LANG["en"])
    speech_config = genai_types.SpeechConfig(
        voice_config=genai_types.VoiceConfig(
            prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                voice_name=_VOICE_NAME,
            ),
        ),
        language_code=bcp47,
    )
    transcription_config = genai_types.AudioTranscriptionConfig(
        language_codes=[bcp47],
    )
    return RunConfig(
        response_modalities=["AUDIO"],
        speech_config=speech_config,
        input_audio_transcription=transcription_config,
        output_audio_transcription=transcription_config,
    )


_build_live_run_config = build_live_run_config
