"""Mock HIS adapter for development and demo environments.

Accepts every visit and logs write-backs instead of sending them. Use
``HttpHisAdapter`` (his_mode="http") to exercise the real integration
against the hospital HIS or the standalone ``hospital-his-mock`` service.
"""

from __future__ import annotations

import logging
from typing import Any

from .adapter import AssignmentResult, PatientHistory, VisitInfo

logger = logging.getLogger(__name__)


class MockHisAdapter:
    def __init__(self) -> None:
        self._queue_seq = 0

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
        request_id: str,
        assign_spid: str,
        sbar: dict[str, str | None] | None = None,
    ) -> AssignmentResult:
        self._queue_seq += 1
        logger.info(
            "[MockHIS] assignment visit=%s spid=%s request_id=%s sbar=%s",
            visit_id, assign_spid, request_id, bool(sbar),
        )
        # A plausible queue number so HIS_MODE=mock demos still show the nurse
        # something to hand the patient.
        return AssignmentResult(
            status="pushed",
            request_id=request_id,
            queue_number=f"A{self._queue_seq:03d}",
            visit_queue_id=f"VQ-MOCK{self._queue_seq:04d}",
            queue_status="WAITING",
            sbar_id="SBAR-MOCK" if sbar else None,
            http_status=200,
        )
