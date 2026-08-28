from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this package, not the process working directory —
# launching uvicorn from the monorepo root must load the same config as
# launching it from hospital-hotline-assistant-api/ (a cwd-dependent .env
# silently booted the app with default settings: HIS in mock mode, no API
# key, wrong model config).
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    app_name: str = "Hospital Hotline Assistant API"
    environment: str = "development"
    database_url: str = "postgresql://postgres:postgres@localhost:5432/hospital_hotline"
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]
    mock_notifier_enabled: bool = True
    notification_webhook_url: str | None = None
    alert_severity_threshold: str = "emergency"
    alert_cooldown_seconds: int = 300
    google_cloud_project: str | None = None
    # "global" routes Gemini calls across Google's region fleet — separate
    # (larger) quota pool, fewer 429 RESOURCE_EXHAUSTED. Regional values still
    # work but pin quota to one region. (Gemini preview models are global-only.)
    google_cloud_location: str = "global"
    # General Gemini model for non-triage features (e.g. surveillance extraction).
    google_model_name: str = "gemini-3.5-flash"
    google_application_credentials: str | None = None
    google_ai_enabled: bool = True
    google_genai_use_vertexai: bool = True
    bp_device_name: str = "hem-7280t"
    bp_device_mac: str | None = None
    bp_omblepy_dir: str | None = None
    bp_python_bin: str | None = None
    bp_fetch_timeout_seconds: int = 120
    # BLE thermometer (standard Health Thermometer Service, e.g. TAIDOC TD1242).
    temp_device_name: str = "TAIDOC TD1242"
    temp_device_mac: str | None = None
    temp_fetch_timeout_seconds: int = 90
    # BLE fingertip pulse oximeter (Rossmax SB210, advertises as RM_SPO2).
    spo2_device_name: str = "Rossmax SB210"
    spo2_device_mac: str | None = None
    spo2_fetch_timeout_seconds: int = 60
    embed_model: str = "intfloat/multilingual-e5-small"
    triage_manual_path: str = "app/data/triage_manual.pdf"
    pgvector_table: str = "triage_knowledge"
    pgvector_embed_dim: int = 384
    rag_query_timeout_seconds: float = 1.0
    rag_query_prewarm_on_startup: bool = True
    # Probe the LLM/STT/TTS legs once at boot and log a PASS/FAIL banner.
    # Three small calls; turn it off for offline test runs or if the extra
    # startup traffic to a metered cloud provider is unwelcome.
    ai_selfcheck_on_startup: bool = True
    # ── AI mode: one switch for the LLM + STT + TTS backends ────────────────
    # "cloud"  — Gemini on Vertex AI + Google Cloud STT/TTS.
    # "local"  — everything served on-prem by the local-ai gateway; no patient
    #            text or audio leaves the building.
    # "custom" — leave the individual *_provider settings below alone (mixed
    #            deployments, e.g. local STT with cloud phrasing).
    # Setting anything other than "custom" OVERRIDES the three provider fields,
    # so the mode is the single source of truth and they cannot drift apart.
    ai_mode: str = "custom"
    # Per-mode model names, so switching does not require also editing the
    # model name (a Gemini id is meaningless to Ollama and vice versa).
    cloud_screening_model_name: str = "gemini-3.1-flash-lite"
    local_screening_model_name: str = "scb10x/llama3.1-typhoon2-8b-instruct"
    # Base URL of the on-prem gateway (STT + TTS + LLM on one port). In local
    # mode this fills in any of the three URLs left unset.
    local_ai_base_url: str = "http://localhost:8090/v1"

    # Deterministic screening engine (LangGraph) — the only triage/voice engine.
    screening_model_provider: str = "vertexai"
    # gemini-3.1-flash-lite (GA): fastest structured-output Gemini as of Jul
    # 2026 — benchmarked ~1.6s extraction / ~0.9s paraphrase vs 4.7s on
    # gemini-2.5-flash with default thinking (and 2.5 retires 2026-10-16).
    screening_model_name: str = "gemini-3.1-flash-lite"
    # Sampling temperature for ALL screening-model families — extraction must
    # be as deterministic as sampling allows, whatever model serves it.
    screening_model_temperature: float = 0.1
    # Gemini 3+ reasoning depth: minimal|low|medium|high. "minimal" is the
    # latency floor (equivalent of thinking_budget=0 on 2.5 models). Ignored
    # for non-Gemini-3 models (they get thinking_budget=0 instead).
    screening_thinking_level: str | None = "minimal"
    screening_openai_base_url: str | None = None
    screening_openai_api_key: str | None = None
    screening_prompt_version: str = "v1"
    screening_question_budget: int = 8
    # Voice turn endpointing — tunable without a code change (restart to apply).
    # silence_hang: ms of silence after speech that ends the caller's turn.
    #   Higher = fewer mid-thought cut-offs but slower; lower = snappier but
    #   more truncated answers.
    # amplitude_threshold: MINIMUM mic level counted as speech. The effective
    #   gate is max(threshold, noise_gate_factor × rolling noise floor), so a
    #   noisy booth raises it automatically. Keep the minimum LOW: browser
    #   auto-gain ramps up over the first seconds of a call, and a high fixed
    #   gate (the old 600) silently dropped the caller's first utterance.
    #   A too-low gate only costs an occasional empty STT turn, which the
    #   bridge already discards silently.
    # min_turn_audio: drop blips shorter than this.
    # Avatar TTS voices — Chirp 3 HD "Leda" (youthful female) in BOTH
    # languages so the nurse avatar is the same person in th and en.
    # Override per-deployment without a code change; any voice from
    # `list_voices` works (Neural2 fallbacks: th-TH-Neural2-C / en-US-Neural2-F).
    tts_voice_th: str = "th-TH-Chirp3-HD-Leda"
    tts_voice_en: str = "en-US-Chirp3-HD-Leda"
    # Speech backends (app/services/speech_adapter.py): "google" (default,
    # Cloud STT/TTS) or "openai_compatible" — any OpenAI-audio-compatible HTTP
    # server (faster-whisper-server/Speaches, kokoro-fastapi/openedai-speech)
    # so patient AUDIO never leaves the hospital. Base URLs include /v1.
    stt_provider: str = "google"
    stt_base_url: str | None = None
    stt_model: str = "whisper-1"
    stt_api_key: str | None = None
    tts_provider: str = "google"
    tts_base_url: str | None = None
    tts_model: str = "tts-1"
    tts_api_key: str | None = None
    # Local voices, per language (the Chirp names above are Google-only).
    # The local gateway has NO language field on /v1/audio/speech — the voice
    # name IS the language selector, so these must be 'th'/'en'. They used to
    # default to "alloy" (an OpenAI voice name, right for kokoro-fastapi and
    # friends but meaningless to local-speech), which silently resolved to
    # English and spoke Thai text in the English voice. Override per
    # deployment if the server on the other end wants real voice names.
    tts_local_voice_th: str = "th"
    tts_local_voice_en: str = "en"
    speech_http_timeout_s: float = 30.0
    # ── In-process speech (STT_PROVIDER/TTS_PROVIDER = "local") ────────────
    # Runs the models inside the backend instead of over HTTP. The point is
    # the network: patient audio is the biggest, most latency-sensitive
    # payload we send, and a dropped STT call costs the whole turn. With
    # "local" only the LLM stays remote.
    #
    # STT — faster-whisper (ctranslate2, not torch). device "auto" picks CUDA
    # when the wheels are there and falls back to CPU; on Apple silicon there
    # is no CUDA, so cpu/int8 is the real setting.
    stt_local_model: str = "large-v3-turbo"
    stt_local_device: str = "auto"
    stt_local_compute_type: str = "int8"
    # Greedy decode: a booth turn is one short utterance, and beam search buys
    # accuracy with latency the patient sits through.
    stt_local_beam_size: int = 1
    # TTS — F5-TTS-THAI. Voice CLONING, so both of these are required: the
    # clip supplies the voice, its transcript supplies the alignment, and the
    # language comes from the text — one clip gives the same nurse in th+en.
    tts_local_model: str = "v1"
    tts_local_device: str = "cpu"
    tts_ref_audio_th: str | None = None
    tts_ref_text_th: str | None = None
    # English falls back to the Thai clip on purpose (same nurse, both
    # languages); set these only for a separate English reference.
    tts_ref_audio_en: str | None = None
    tts_ref_text_en: str | None = None
    # 32 steps / cfg 2.0 are the F5 defaults. Steps is the latency dial —
    # fewer is faster and rougher.
    tts_f5_steps: int = 32
    tts_f5_cfg: float = 2.0
    # Slightly under 1.0 reads as an unhurried nurse and is easier to follow
    # in a noisy booth.
    tts_speed_th: float = 0.95
    tts_speed_en: float = 1.0
    # Button-first turn taking (product decision 2026-07-27): the patient
    # ends their turn with "I'm finished speaking". Silence auto-detect is
    # only a safety net for patients who never tap — long enough that it
    # can't race a normal tap mid-thought.
    voice_silence_hang_ms: int = 8000
    voice_speech_amplitude_threshold: int = 250
    voice_noise_gate_factor: float = 3.5
    voice_min_turn_audio_ms: int = 500
    # hard wall-clock cap per LLM call (seconds). Vertex/Gemini gRPC has no
    # client deadline by default, so a stalled response would hang the turn
    # (and any voice call) forever; this bounds it and the node falls back.
    screening_model_timeout_s: float = 30.0
    # HIS integration. "mock" logs referrals and accepts every visit;
    # "http" talks to the hospital HIS API (or the hospital-his-mock service).
    his_mode: str = "mock"
    his_base_url: str | None = None
    his_api_key: str | None = None
    his_timeout_seconds: float = 5.0
    # Shown as the Hospital Database panel title once an admin establishes
    # the connection (admin → Database Settings).
    his_display_name: str = "Hospital DB"
    # extra="ignore" so retired env vars (e.g. TRIAGE_ENGINE / VOICE_ENGINE
    # from older .env files) don't break startup.
    @field_validator("google_application_credentials", "triage_manual_path")
    @classmethod
    def _anchor_relative_paths(cls, value: str | None) -> str | None:
        """Resolve relative file paths against the API root, not the cwd.

        `.env` conventionally holds paths like ``./phoenix_gcp_credentials.json``;
        launching uvicorn from the monorepo root must find the same files as
        launching from hospital-hotline-assistant-api/ (a cwd-relative
        credentials path broke TTS/STT with DefaultCredentialsError).
        """
        if not value:
            return value
        path = Path(value)
        if not path.is_absolute():
            path = _ENV_FILE.parent / path
        return str(path)

    @model_validator(mode="after")
    def _apply_ai_mode(self):
        """Resolve AI_MODE into the three provider fields.

        Done here rather than in the adapters so that every entry point — the
        app, the eval harness, any script — sees one consistent set of
        providers, and so `settings.stt_provider` stays the single thing the
        adapters read.
        """
        mode = (self.ai_mode or "custom").strip().lower()
        if mode == "custom":
            return self
        if mode not in ("local", "cloud"):
            raise ValueError(
                f"AI_MODE must be 'local', 'cloud' or 'custom', got {self.ai_mode!r}"
            )

        if mode == "cloud":
            self.screening_model_provider = "vertexai"
            self.stt_provider = "google"
            self.tts_provider = "google"
            self.screening_model_name = self.cloud_screening_model_name
        else:
            self.screening_model_provider = "openai_compatible"
            # A mode is a DEFAULT, not an override: an explicitly configured
            # provider wins, exactly as the explicit per-service URLs below
            # already do. That is what lets AI_MODE=local mean "local LLM"
            # while STT_PROVIDER/TTS_PROVIDER=local run the speech models
            # in-process — without it, setting both silently reverts speech
            # to HTTP and the .env reads as though it did something else.
            if "stt_provider" not in self.model_fields_set:
                self.stt_provider = "openai_compatible"
            if "tts_provider" not in self.model_fields_set:
                self.tts_provider = "openai_compatible"
            self.screening_model_name = self.local_screening_model_name
            # One gateway serves all three; explicit per-service URLs still win
            # so a split deployment (separate STT box) stays possible.
            self.screening_openai_base_url = (
                self.screening_openai_base_url or self.local_ai_base_url
            )
            self.stt_base_url = self.stt_base_url or self.local_ai_base_url
            self.tts_base_url = self.tts_base_url or self.local_ai_base_url
            # The OpenAI client rejects an empty key even when the server
            # ignores it entirely.
            self.screening_openai_api_key = self.screening_openai_api_key or "local"
        return self

    @model_validator(mode="after")
    def _normalise_openai_base_urls(self):
        """Every OpenAI-compatible base URL must end in /v1.

        The clients append their own path — ``ChatOpenAI`` adds
        ``/chat/completions``, ``HttpSttClient`` adds ``/audio/transcriptions``,
        ``HttpTtsClient`` adds ``/audio/speech``. A base URL without the suffix
        therefore 404s at request time, not at startup, and reads as "the
        gateway is down" when the gateway is fine. Observed in the field: STT
        and TTS worked while every LLM call 404'd on ``/chat/completions``,
        because only that one URL had been written without ``/v1``.

        Normalising here rather than in each adapter means one rule for all
        three, and it also covers the URLs AI_MODE fills in.
        """
        for field in (
            "screening_openai_base_url",
            "stt_base_url",
            "tts_base_url",
        ):
            url = (getattr(self, field, None) or "").strip()
            if not url:
                continue
            fixed = url.rstrip("/")
            if not fixed.endswith("/v1"):
                fixed = f"{fixed}/v1"
            if fixed != url:
                setattr(self, field, fixed)
        return self

    @model_validator(mode="after")
    def _check_provider_coherence(self):
        """Fail at startup on a provider that cannot possibly work.

        Mostly guards AI_MODE=custom, where nothing stops an
        ``openai_compatible`` provider being left without a base URL — which
        otherwise surfaces mid-call as an obscure client error instead of a
        clear boot failure.
        """
        missing = [
            name
            for name, provider, url in (
                ("SCREENING_OPENAI_BASE_URL", self.screening_model_provider,
                 self.screening_openai_base_url),
                ("STT_BASE_URL", self.stt_provider, self.stt_base_url),
                ("TTS_BASE_URL", self.tts_provider, self.tts_base_url),
            )
            if provider == "openai_compatible" and not url
        ]
        if missing:
            raise ValueError(
                f"provider is 'openai_compatible' but {', '.join(missing)} is unset. "
                "Set AI_MODE=local to point all three at LOCAL_AI_BASE_URL, or set "
                "the URL(s) explicitly."
            )
        return self

    @property
    def ai_mode_summary(self) -> dict[str, str]:
        """What the resolved mode actually points at — for /health and logs."""
        return {
            "mode": self.ai_mode,
            "llm": f"{self.screening_model_provider}:{self.screening_model_name}",
            "stt": self.stt_provider,
            "tts": self.tts_provider,
        }

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

settings = Settings()
