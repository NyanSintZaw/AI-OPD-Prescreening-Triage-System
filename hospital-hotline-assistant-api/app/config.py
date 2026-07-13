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
    google_cloud_location: str = "us-central1"
    # General Gemini model for non-triage features (e.g. surveillance extraction).
    google_model_name: str = "gemini-2.5-flash"
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
    screening_model_name: str = "gemini-2.5-flash"
    screening_openai_base_url: str | None = None
    screening_openai_api_key: str | None = None
    screening_prompt_version: str = "v1"
    screening_question_budget: int = 8
    # Voice turn endpointing — tunable without a code change (restart to apply).
    # silence_hang: ms of silence after speech that ends the caller's turn.
    #   Higher = fewer mid-thought cut-offs but slower; lower = snappier but
    #   more truncated answers. amplitude_threshold: mic level counted as
    #   speech (higher ignores room noise). min_turn_audio: drop blips shorter
    #   than this.
    voice_silence_hang_ms: int = 2500
    voice_speech_amplitude_threshold: int = 600
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
    # extra="ignore" so retired env vars (e.g. TRIAGE_ENGINE / VOICE_ENGINE
    # from older .env files) don't break startup.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

settings = Settings()
