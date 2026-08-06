"""Hospital Information System integration adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .adapter import AssignmentResult, HisAdapter, PatientHistory, VisitInfo
from .department_map import his_department_name, his_service_point
from .http_adapter import HttpHisAdapter, his_auth_headers
from .mock import MockHisAdapter

if TYPE_CHECKING:
    from app.config import Settings

__all__ = [
    "AssignmentResult",
    "HisAdapter",
    "VisitInfo",
    "PatientHistory",
    "MockHisAdapter",
    "HttpHisAdapter",
    "his_auth_headers",
    "his_department_name",
    "his_service_point",
    "build_his_adapter",
]


def build_his_adapter(settings: "Settings") -> HisAdapter:
    """Construct the HIS adapter chosen by config.

    ``his_mode="http"`` requires ``his_base_url``; anything else (or a
    missing base URL) falls back to the mock so the app always boots.
    """
    if settings.his_mode == "http" and settings.his_base_url:
        return HttpHisAdapter(
            base_url=settings.his_base_url,
            api_key=settings.his_api_key,
            timeout=settings.his_timeout_seconds,
        )
    return MockHisAdapter()
