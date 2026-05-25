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
    ]
    slack_webhook_url: str | None = None
    alert_severity_threshold: str = "emergency"
    alert_cooldown_seconds: int = 300
    google_cloud_project: str | None = None
    google_cloud_location: str = "us-central1"
    google_model_name: str = "gemini-2.5-flash"
    google_application_credentials: str | None = None
    google_ai_enabled: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()