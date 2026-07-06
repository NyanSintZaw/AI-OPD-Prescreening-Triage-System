"""Mock HIS adapter for development and demo environments."""

from __future__ import annotations

import logging
from typing import Any

from .adapter import VisitInfo

logger = logging.getLogger(__name__)


class MockHisAdapter:
    """Accepts every visit id and logs referral pushes instead of sending."""

    async def validate_visit(self, visit_id: str) -> VisitInfo | None:
        if not visit_id.strip():
            return None
        return VisitInfo(
            visit_id=visit_id.strip(),
            patient_id=None,
            patient_name=None,
            is_active=True,
            raw={"source": "mock"},
        )

    async def get_departments(self) -> list[dict[str, Any]]:
        return []

    async def push_referral(self, referral: dict[str, Any]) -> bool:
        logger.info("[MockHIS] referral push: %s", referral)
        return True
