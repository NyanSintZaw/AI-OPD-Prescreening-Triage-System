"""Mock HIS adapter for development and demo environments.

Accepts every visit and logs write-backs instead of sending them. Use
``HttpHisAdapter`` (his_mode="http") to exercise the real integration
against the hospital HIS or the standalone ``hospital-his-mock`` service.
"""

from __future__ import annotations

import logging
from typing import Any

from .adapter import VisitInfo

logger = logging.getLogger(__name__)


class MockHisAdapter:
    async def validate_visit(self, visit_id: str) -> VisitInfo | None:
        if not visit_id.strip():
            return None
        return VisitInfo(
            visit_id=visit_id.strip(),
            is_active=True,
            raw={"source": "mock"},
        )

    async def get_departments(self) -> list[dict[str, Any]]:
        return []

    async def push_referral(self, referral: dict[str, Any]) -> bool:
        logger.info("[MockHIS] stage-1 referral push: %s", referral)
        return True

    async def confirm_routing(
        self,
        visit_id: str,
        *,
        department: str,
        complaint: str | None = None,
        note: str | None = None,
        confirmed_by: str,
        rerouted: bool = False,
    ) -> bool:
        logger.info(
            "[MockHIS] stage-2 routing %s visit=%s dept=%s by=%s complaint=%s note=%s",
            "reroute" if rerouted else "confirm",
            visit_id,
            department,
            confirmed_by,
            complaint,
            note,
        )
        return True
