"""Mock HIS adapter for development and demo environments.

Accepts every visit and logs write-backs instead of sending them. Use
``HttpHisAdapter`` (his_mode="http") to exercise the real integration
against the hospital HIS or the standalone ``hospital-his-mock`` service.
"""

from __future__ import annotations

import logging
from typing import Any

from .adapter import PatientHistory, VisitInfo

logger = logging.getLogger(__name__)


class MockHisAdapter:
    async def validate_visit(self, visit_id: str) -> VisitInfo | None:
        if not visit_id.strip():
            return None
        return VisitInfo(
            visit_id=visit_id.strip(),
            is_active=True,
            patient_name="Mock Patient",
            patient_history=PatientHistory(is_first_time=True),
            raw={"source": "mock"},
        )

    async def get_departments(self) -> list[dict[str, Any]]:
        return []

    async def push_referral(self, referral: dict[str, Any]) -> bool:
        logger.info("[MockHIS] stage-1 referral push: %s", referral)
        return True

    async def push_patient_history(self, hn: str, history: dict[str, Any]) -> bool:
        logger.info("[MockHIS] patient history push hn=%s history=%s", hn, history)
        return True

    async def push_follow_up(self, visit_id: str, follow_up: str) -> bool:
        logger.info(
            "[MockHIS] follow-up push visit=%s text=%s", visit_id, follow_up
        )
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
