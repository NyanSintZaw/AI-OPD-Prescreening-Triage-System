"""Mock HIS adapter for development and demo environments.

Accepts every HN and logs write-backs instead of sending them. Use
``HttpHisAdapter`` (his_mode="http") to exercise the real integration
against the hospital HIS or the standalone ``hospital-his-mock`` service.
"""

from __future__ import annotations

import logging
from typing import Any

from .adapter import AssignmentResult, PatientHistory, PatientInfo

logger = logging.getLogger(__name__)


class MockHisAdapter:
    def __init__(self) -> None:
        self._queue_seq = 0

    async def validate_patient(self, hn: str) -> PatientInfo | None:
        if not hn.strip():
            return None
        return PatientInfo(
            hn=hn.strip(),
            patient_name="Mock Patient",
            patient_history=PatientHistory(is_first_time=True),
            current_visit=None,  # no VN passthrough — write-backs go HN-only
            raw={"source": "mock"},
        )

    async def push_prescreen(self, prescreen: dict[str, Any]) -> bool:
        logger.info("[MockHIS] stage-1 prescreen push: %s", prescreen)
        return True

    async def push_patient_history(self, hn: str, history: dict[str, Any]) -> bool:
        logger.info("[MockHIS] patient history push hn=%s history=%s", hn, history)
        return True

    async def push_patient_gender(self, hn: str, gender: str) -> bool:
        logger.info("[MockHIS] patient gender push hn=%s gender=%s", hn, gender)
        return True

    async def confirm_routing(
        self,
        visit_id: str | None,
        *,
        request_id: str,
        hn: str | None,
        base_department_id: str,
        sbar: dict[str, str | None] | None = None,
        mfu_prescreen: dict[str, Any] | None = None,
    ) -> AssignmentResult:
        self._queue_seq += 1
        logger.info(
            "[MockHIS] assignment hn=%s visit=%s dept=%s request_id=%s sbar=%s mfu=%s",
            hn, visit_id, base_department_id, request_id, bool(sbar), bool(mfu_prescreen),
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
