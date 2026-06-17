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
    realtime_input_config = genai_types.RealtimeInputConfig(
        # The call UI has an explicit "Send" button. Disable automatic
        # VAD and bracket each caller turn with activity_start/end so
        # Gemini Live knows exactly when to respond.
        automatic_activity_detection=genai_types.AutomaticActivityDetection(
            disabled=True,
            start_of_speech_sensitivity=genai_types.StartSensitivity.START_SENSITIVITY_HIGH,
            end_of_speech_sensitivity=genai_types.EndSensitivity.END_SENSITIVITY_HIGH,
            prefix_padding_ms=300,
            silence_duration_ms=700,
        ),
        activity_handling=genai_types.ActivityHandling.NO_INTERRUPTION,
        turn_coverage=genai_types.TurnCoverage.TURN_INCLUDES_ALL_INPUT,
    )
    return RunConfig(
        response_modalities=["AUDIO"],
        speech_config=speech_config,
        input_audio_transcription=transcription_config,
        output_audio_transcription=transcription_config,
        realtime_input_config=realtime_input_config,
    )


_build_live_run_config = build_live_run_config
