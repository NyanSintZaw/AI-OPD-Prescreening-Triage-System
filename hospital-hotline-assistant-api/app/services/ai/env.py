"""Google GenAI / Vertex environment setup."""

from __future__ import annotations

import os
from pathlib import Path

from app.config import settings

# app/services/ai/env.py -> the backend root, where .env's relative
# credential path is anchored.
_BACKEND_ROOT = Path(__file__).resolve().parents[3]


def configure_google_genai_environment() -> None:
    """Mirror Pydantic settings into env vars read by google-genai / ADK."""

    if settings.google_genai_use_vertexai:
        os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
    if settings.google_cloud_project:
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", settings.google_cloud_project)
    if settings.google_cloud_location:
        os.environ.setdefault("GOOGLE_CLOUD_LOCATION", settings.google_cloud_location)
    if settings.google_application_credentials:
        # Resolve against the backend root, not the cwd: .env ships a relative
        # path, so a script run from anywhere else silently fell back to
        # gcloud ADC and got 403 from Vertex.
        cred = Path(settings.google_application_credentials)
        if not cred.is_absolute():
            cred = _BACKEND_ROOT / cred
        os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(cred))
