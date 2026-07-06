"""HIS integration adapter protocol.

The real hospital HIS (iMed) API is not yet available; the engine and
services depend only on this protocol so the concrete implementation can be
swapped in via config without touching call sites (SRS §5.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class VisitInfo:
    visit_id: str
    patient_id: str | None
    patient_name: str | None
    is_active: bool
    raw: dict[str, Any] | None = None


class HisAdapter(Protocol):
    async def validate_visit(self, visit_id: str) -> VisitInfo | None:
        """Verify a visit id against the HIS; None when unknown/inactive."""

    async def get_departments(self) -> list[dict[str, Any]]:
        """Approved department names/locations from the HIS, when supported."""

    async def push_referral(self, referral: dict[str, Any]) -> bool:
        """Send the validated pre-screening referral summary to the HIS."""
