from pydantic_settings import BaseSettings, SettingsConfigDict

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
    embed_model: str = "intfloat/multilingual-e5-small"
    triage_manual_path: str = "app/data/triage_manual.pdf"
    pgvector_table: str = "triage_knowledge"
    pgvector_embed_dim: int = 384
    rag_query_timeout_seconds: float = 1.0
    rag_query_prewarm_on_startup: bool = True
    # Deterministic screening engine (LangGraph) — the only triage/voice engine.
    screening_model_provider: str = "vertexai"
    # gemini-3.1-flash-lite (GA): fastest structured-output Gemini as of Jul
    # 2026 — benchmarked ~1.6s extraction / ~0.9s paraphrase vs 4.7s on
    # gemini-2.5-flash with default thinking (and 2.5 retires 2026-10-16).
    screening_model_name: str = "gemini-3.1-flash-lite"
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
    voice_silence_hang_ms: int = 2500
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
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

settings = Settings()
