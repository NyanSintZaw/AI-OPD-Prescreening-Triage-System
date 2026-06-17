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
    # Toggle the in-process mock notification sink that logs emergency
    # dispatches to stdout instead of calling an external system. Stays
    # on by default until LINE / FCM / SMS integration lands.
    mock_notifier_enabled: bool = True
    # Generic webhook URL placeholder for the upcoming LINE / FCM / SMS
    # notification pipeline. Leave as None to use the mock notifier.
    notification_webhook_url: str | None = None
    alert_severity_threshold: str = "emergency"
    alert_cooldown_seconds: int = 300
    google_cloud_project: str | None = None
    google_cloud_location: str = "us-central1"
    # Text / chat mode model. ``gemini-2.5-pro`` is the highest GA Pro-tier
    # model on Vertex AI as of May 2026 — top quality, supports streaming,
    # tool calls, and multimodal, and works on standard (non-preview-gated)
    # Vertex projects. To try preview tiers like ``gemini-3.1-pro-preview``
    # or the newer ``gemini-3.5-flash``, override ``GOOGLE_MODEL_NAME`` in
    # ``.env`` after confirming your project's been allowlisted.
    google_model_name: str = "gemini-2.5-pro"
    # Live API (voice WebSocket) model. The Gemini Live API has its own
    # dedicated model family — Pro tier is NOT available for live audio
    # on Vertex. ``gemini-live-2.5-flash-native-audio`` is the only GA
    # Live model as of May 2026 (released Dec 2025, retires Dec 2026).
    google_live_model_name: str = "gemini-live-2.5-flash-native-audio"
    google_application_credentials: str | None = None
    live_debug_audio: bool = False
    # ADK now drives the triage agent and assumes Google AI is online,
    # so the default flips on. Override to False in non-AI test envs.
    google_ai_enabled: bool = True
    # Route google-genai (and ADK underneath) through Vertex AI instead of
    # the Gemini API. When True we authenticate with the service-account
    # JSON in ``google_application_credentials`` + project/location above;
    # no API key is needed. The companion env var ``GOOGLE_GENAI_USE_VERTEXAI``
    # is exported into ``os.environ`` by ``adk_agent`` so the underlying
    # google-genai client sees it.
    google_genai_use_vertexai: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()