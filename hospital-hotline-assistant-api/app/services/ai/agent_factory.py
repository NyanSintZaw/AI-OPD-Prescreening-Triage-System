"""ADK agent construction for hotline triage."""

from __future__ import annotations

from app.config import settings
from app.services.ai.env import configure_google_genai_environment

configure_google_genai_environment()

from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.adk.tools import FunctionTool  # noqa: E402

from app.services.ai.prompts import (  # noqa: E402
    _ORCHESTRATOR_INSTRUCTION,
    _TRIAGE_INSTRUCTION,
)
from app.services.ai.tools import (  # noqa: E402
    classify_triage_level,
    get_department_list,
    get_triage_reference,
)

APP_NAME: str = "hospital-hotline"
LIVE_APP_NAME: str = "hospital-hotline-live"

# Shared by text and live runners so session behaviour remains unchanged.
_SESSION_SERVICE: InMemorySessionService = InMemorySessionService()


def build_triage_agent(model_name: str | None = None) -> LlmAgent:
    return LlmAgent(
        name="TriageAgent",
        description=(
            "Performs ER Five-Level triage classification. Asks targeted "
            "follow-up questions, consults the decision tree, then records "
            "the final level + department via classify_triage_level."
        ),
        model=model_name or settings.google_model_name,
        instruction=_TRIAGE_INSTRUCTION,
        tools=[
            FunctionTool(get_triage_reference),
            FunctionTool(get_department_list),
            FunctionTool(classify_triage_level),
        ],
    )


def build_orchestrator(
    triage_agent: LlmAgent,
    model_name: str | None = None,
) -> LlmAgent:
    return LlmAgent(
        name="HotlineOrchestrator",
        description=(
            "Routes every hotline turn to the TriageAgent for symptom triage."
        ),
        model=model_name or settings.google_model_name,
        instruction=_ORCHESTRATOR_INSTRUCTION,
        sub_agents=[triage_agent],
    )


# Backward-compatible private names used by the old facade.
_build_triage_agent = build_triage_agent
_build_orchestrator = build_orchestrator
