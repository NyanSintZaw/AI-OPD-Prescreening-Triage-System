"""AI_MODE resolves the three provider fields — and defers to explicit ones.

The mode is a convenience switch, so the failure it invites is silent: a
.env that sets both AI_MODE and a provider reads as though both applied,
while one quietly loses. That matters most for the speech providers, because
"local" (models in this process, audio never on the network) and
"openai_compatible" (audio POSTed to a gateway) differ in where patient
recordings go, not just in speed.

``_env_file=None`` on every construction: without it pydantic-settings reads
the developer's real .env and the assertions track whatever it happens to
contain.
"""

from __future__ import annotations

import pytest

from app.config import Settings

LOCAL_URL = "http://gateway.invalid:8092/v1"


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


class TestLocalMode:
    def test_sets_all_three_providers_when_none_are_explicit(self):
        s = _settings(ai_mode="local", local_ai_base_url=LOCAL_URL)
        assert s.screening_model_provider == "openai_compatible"
        assert s.stt_provider == "openai_compatible"
        assert s.tts_provider == "openai_compatible"

    def test_fans_the_one_url_out_to_every_service(self):
        s = _settings(ai_mode="local", local_ai_base_url=LOCAL_URL)
        assert s.screening_openai_base_url == LOCAL_URL
        assert s.stt_base_url == LOCAL_URL
        assert s.tts_base_url == LOCAL_URL

    def test_explicit_urls_win_over_the_mode(self):
        """A split deployment (speech on a separate box) has to stay possible."""
        s = _settings(
            ai_mode="local",
            local_ai_base_url=LOCAL_URL,
            stt_base_url="http://speech.invalid:9000/v1",
        )
        assert s.stt_base_url == "http://speech.invalid:9000/v1"
        assert s.screening_openai_base_url == LOCAL_URL

    def test_explicit_speech_providers_win_over_the_mode(self):
        """The case this test file exists for.

        AI_MODE=local + STT_PROVIDER=local means "local LLM over HTTP, speech
        models in this process". Before the guard, the mode overwrote both
        providers and patient audio went back over the network — with the
        .env still reading STT_PROVIDER=local.
        """
        s = _settings(
            ai_mode="local",
            local_ai_base_url=LOCAL_URL,
            stt_provider="local",
            tts_provider="local",
        )
        assert s.stt_provider == "local"
        assert s.tts_provider == "local"
        # The LLM is still resolved by the mode.
        assert s.screening_model_provider == "openai_compatible"
        assert s.screening_openai_base_url == LOCAL_URL

    def test_names_the_local_model(self):
        s = _settings(
            ai_mode="local",
            local_ai_base_url=LOCAL_URL,
            local_screening_model_name="some/model:latest",
        )
        assert s.screening_model_name == "some/model:latest"

    def test_supplies_an_api_key_the_openai_client_will_accept(self):
        """The client rejects an empty key even when the server ignores it."""
        s = _settings(ai_mode="local", local_ai_base_url=LOCAL_URL)
        assert s.screening_openai_api_key


class TestOtherModes:
    def test_cloud_mode_routes_everything_to_google(self):
        s = _settings(ai_mode="cloud")
        assert s.screening_model_provider == "vertexai"
        assert s.stt_provider == "google"
        assert s.tts_provider == "google"

    def test_custom_mode_leaves_every_provider_alone(self):
        s = _settings(
            ai_mode="custom",
            screening_model_provider="openai_compatible",
            screening_openai_base_url=LOCAL_URL,
            stt_provider="local",
            tts_provider="google",
        )
        assert s.screening_model_provider == "openai_compatible"
        assert s.stt_provider == "local"
        assert s.tts_provider == "google"

    def test_an_unknown_mode_fails_at_startup_rather_than_at_a_turn(self):
        with pytest.raises(ValueError, match="AI_MODE"):
            _settings(ai_mode="loocal")


class TestSummary:
    def test_reports_the_resolved_providers_not_the_requested_mode(self):
        """/health reads this, so it must show what is really serving."""
        s = _settings(
            ai_mode="local",
            local_ai_base_url=LOCAL_URL,
            local_screening_model_name="m:latest",
            stt_provider="local",
            tts_provider="local",
        )
        assert s.ai_mode_summary == {
            "mode": "local",
            "llm": "openai_compatible:m:latest",
            "stt": "local",
            "tts": "local",
        }
