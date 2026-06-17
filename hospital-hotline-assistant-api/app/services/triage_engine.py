"""Compatibility facade for the refactored triage engine."""

from app.services.ai.triage_engine import LlmTriageEngine
from app.services.ai.triage_models import TriageDecision, TriageEngine

__all__ = [
    "LlmTriageEngine",
    "TriageDecision",
    "TriageEngine",
]
