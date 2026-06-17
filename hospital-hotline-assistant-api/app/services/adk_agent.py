"""Compatibility facade for the refactored ADK hotline implementation."""

from app.services.ai.agent_factory import (
    APP_NAME,
    LIVE_APP_NAME,
    _SESSION_SERVICE,
    _build_orchestrator,
    _build_triage_agent,
    build_orchestrator,
    build_triage_agent,
)
from app.services.ai.live_config import (
    _LANGUAGE_CODE_BY_LANG,
    _VOICE_NAME,
    _build_live_run_config,
    build_live_run_config,
)
from app.services.ai.live_events import _strip_meta_markers
from app.services.ai.live_runner import HotlineADKLiveRunner
from app.services.ai.prompts import (
    _ORCHESTRATOR_INSTRUCTION,
    _TRIAGE_INSTRUCTION,
)
from app.services.ai.reference_data import (
    DATA_DIR,
    _DEPARTMENTS,
    _DEPARTMENTS_FILE,
    _TRIAGE_FILE,
    _TRIAGE_REF,
    get_department_reference_data,
    get_triage_reference_data,
)
from app.services.ai.text_runner import HotlineADKRunner
from app.services.ai.tools import (
    classify_triage_level,
    get_department_list,
    get_triage_reference,
)

__all__ = [
    "APP_NAME",
    "DATA_DIR",
    "LIVE_APP_NAME",
    "HotlineADKLiveRunner",
    "HotlineADKRunner",
    "_DEPARTMENTS",
    "_DEPARTMENTS_FILE",
    "_LANGUAGE_CODE_BY_LANG",
    "_ORCHESTRATOR_INSTRUCTION",
    "_SESSION_SERVICE",
    "_TRIAGE_FILE",
    "_TRIAGE_INSTRUCTION",
    "_TRIAGE_REF",
    "_VOICE_NAME",
    "_build_live_run_config",
    "_build_orchestrator",
    "_build_triage_agent",
    "_strip_meta_markers",
    "build_live_run_config",
    "build_orchestrator",
    "build_triage_agent",
    "classify_triage_level",
    "get_department_list",
    "get_department_reference_data",
    "get_triage_reference",
    "get_triage_reference_data",
]
