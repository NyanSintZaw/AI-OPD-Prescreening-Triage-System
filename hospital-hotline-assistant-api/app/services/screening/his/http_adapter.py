"""HTTP HIS adapter — talks to the hospital HIS REST API (or the
standalone ``hospital-his-mock`` service) over ``httpx``.

Every method is defensive: the patient flow must never break because the
HIS is slow or down. Reads return ``None`` on failure; write-backs return
``False`` and log — the caller treats that as "not yet synced", not fatal.
"""

from __future__ import annotations

import datetime as _dt
import logging
from typing import Any

import httpx

from .adapter import AssignmentResult, PatientHistory, VisitInfo

logger = logging.getLogger(__name__)

# The hospital's assignment endpoint. Their UAT/PROD base URLs are documented
# with the /api/v1 suffix already on them — configure HIS_BASE_URL WITHOUT it,
# the way the mock is mounted at http://localhost:8001.
ASSIGNMENTS_PATH = "/api/v1/patient-assignments"


def his_auth_headers(api_key: str | None) -> dict[str, str]:
    """Auth headers for HIS calls. Sends both schemes so one config works
    everywhere: the real iMed API wants ``Authorization: Bearer``; the
    ``hospital-his-mock`` convention is ``X-API-Key``."""
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}", "X-API-Key": api_key}


def _parse_patient_history(patient: dict[str, Any] | None) -> PatientHistory | None:
    """Parse the ``visit_payload()``-nested ``"patient"`` object (mock HIS's
    ``GET /api/visits/{id}``) into a ``PatientHistory``. None when the HIS
    doesn't support/return HN-level data."""
    if not patient:
        return None
    history = patient.get("history") or {}
    last_vitals = patient.get("last_vitals") or {}
    return PatientHistory(
        is_first_time=bool(patient.get("is_first_time", True)),
        smoking_alcohol=history.get("smoking_alcohol"),
        allergies=history.get("allergies"),
        chronic_conditions=history.get("chronic_conditions"),
        past_surgeries=history.get("past_surgeries"),
        family_history=history.get("family_history"),
        recorded_at=history.get("recorded_at"),
        last_weight_kg=last_vitals.get("weight"),
        last_height_cm=last_vitals.get("height"),
        vitals_measured_at=last_vitals.get("measured_at"),
    )


def _age_from_birthdate(birthdate: str | None) -> int | None:
    if not birthdate:
        return None
    try:
        born = _dt.date.fromisoformat(birthdate.strip()[:10])
    except ValueError:
        return None
    today = _dt.date.today()
    years = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    return years if 0 <= years <= 130 else None


class HttpHisAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 5.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = his_auth_headers(api_key)
        self._timeout = timeout
        self._client = client  # injectable for tests (ASGI transport)

    async def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> httpx.Response | None:
        url = f"{self._base_url}{path}"
        try:
            if self._client is not None:
                return await self._client.request(
                    method, url, headers=self._headers, timeout=self._timeout, **kwargs
                )
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.request(
                    method, url, headers=self._headers, **kwargs
                )
        except httpx.HTTPError as exc:
            logger.warning("[HIS] %s %s failed: %s", method, path, exc)
            return None

    async def validate_visit(self, visit_id: str) -> VisitInfo | None:
        if not visit_id.strip():
            return None
        resp = await self._request("GET", f"/api/visits/{visit_id.strip()}")
        if resp is None or resp.status_code == 404:
            return None
        if resp.status_code != 200:
            logger.warning("[HIS] validate_visit %s → %s", visit_id, resp.status_code)
            return None
        data = resp.json()
        birthdate = data.get("birthdate")
        return VisitInfo(
            visit_id=data.get("visit_id", visit_id),
            # Prefer "hn" (the field name we standardized on in the mock
            # HIS); fall back to "hnx" in case the real hospital HIS export
            # only carries that name (see docs/his-integration.md §6.1).
            patient_id=data.get("hn") or data.get("hnx"),
            patient_name=data.get("patient_name"),
            is_active=True,
            birthdate=birthdate,
            age_years=_age_from_birthdate(birthdate),
            vitals=data.get("vitals") or {},
            appointment=bool(data.get("appointment")),
            patient_history=_parse_patient_history(data.get("patient")),
            raw=data,
        )

    async def push_referral(self, referral: dict[str, Any]) -> bool:
        visit_id = referral.get("visit_id")
        if not visit_id:
            return False
        resp = await self._request(
            "POST", f"/api/visits/{visit_id}/prescreen", json=referral
        )
        if resp is None or resp.status_code not in (200, 201):
            logger.warning(
                "[HIS] push_referral visit=%s → %s",
                visit_id,
                None if resp is None else resp.status_code,
            )
            return False
        return True

    async def push_patient_history(self, hn: str, history: dict[str, Any]) -> bool:
        resp = await self._request(
            "PUT", f"/api/patients/{hn}/history", json=history
        )
        if resp is None or resp.status_code != 200:
            logger.warning(
                "[HIS] push_patient_history hn=%s → %s",
                hn,
                None if resp is None else resp.status_code,
            )
            return False
        return True

    async def push_follow_up(self, visit_id: str, follow_up: str) -> bool:
        resp = await self._request(
            "PUT",
            f"/api/visits/{visit_id}/follow-up",
            json={"follow_up": follow_up},
        )
        if resp is None or resp.status_code != 200:
            logger.warning(
                "[HIS] push_follow_up visit=%s → %s",
                visit_id,
                None if resp is None else resp.status_code,
            )
            return False
        return True

    async def confirm_routing(
        self,
        visit_id: str,
        *,
        request_id: str,
        assign_spid: str,
        sbar: dict[str, str | None] | None = None,
    ) -> AssignmentResult:
        body: dict[str, Any] = {
            "request_id": request_id,
            "visit_id": visit_id,
            "assign_spid": assign_spid,
        }
        # Omitted on purpose: queue_number (their queue rules own sequencing),
        # base_department_id (they derive it from the service point) and
        # assign_eid (we route to a department, never a named doctor).
        if sbar and any(v for v in sbar.values()):
            body["sbar"] = {k: v for k, v in sbar.items() if v}

        resp = await self._request("POST", ASSIGNMENTS_PATH, json=body)
        if resp is None:
            # Transport error or timeout: the queue row MAY have been created.
            # Never report this as a failure — see AssignmentResult.
            logger.warning("[HIS] assignment visit=%s → no response", visit_id)
            return AssignmentResult(status="unknown", request_id=request_id)

        try:
            payload = resp.json()
        except ValueError:
            logger.warning("[HIS] assignment visit=%s → non-JSON body", visit_id)
            return AssignmentResult(
                status="unknown", request_id=request_id, http_status=resp.status_code
            )

        result = payload.get("result") or {}

        def build(status: str, *, with_queue: bool = False) -> AssignmentResult:
            # Echo their request_id when they send one, but never let it be
            # None — it is the key a retry depends on.
            return AssignmentResult(
                status=status,
                request_id=str(payload.get("request_id") or request_id),
                http_status=resp.status_code,
                message=payload.get("message"),
                message_th=payload.get("message_th"),
                queue_number=result.get("queue_number") if with_queue else None,
                visit_queue_id=result.get("visit_queue_id") if with_queue else None,
                queue_status=result.get("queue_status") if with_queue else None,
                sbar_id=result.get("sbar_id") if with_queue else None,
                assign_eid=result.get("assign_eid") if with_queue else None,
            )

        if resp.is_success:
            if payload.get("status") == "STATUS_SUCCESS":
                return build("pushed", with_queue=True)
            return build("invalid")
        if resp.status_code == 409:
            # Already queued — our earlier attempt landed, so this IS success.
            # `result` is only present if the hospital adopts change request 7;
            # without it the nurse must look the number up in iMed.
            return build("pushed", with_queue=True)
        if resp.status_code == 403:
            return build("denied")
        if resp.status_code == 422:
            # Only their business error means "destination closed". A framework
            # validation 422 would otherwise tell the nurse to reroute when the
            # real problem is our payload.
            if payload.get("message") == "SERVICE_POINT_NOT_AVAILABLE":
                return build("unavailable")
            return build("invalid")
        if resp.status_code == 400:
            return build("invalid")
        # 5xx and anything else: the row may exist, so treat it as unknown.
        return build("unknown")
