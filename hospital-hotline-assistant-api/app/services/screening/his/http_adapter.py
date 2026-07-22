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

from .adapter import PatientHistory, VisitInfo

logger = logging.getLogger(__name__)


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
        self._headers = {"X-API-Key": api_key} if api_key else {}
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

    async def get_departments(self) -> list[dict[str, Any]]:
        resp = await self._request("GET", "/api/departments")
        if resp is None or resp.status_code != 200:
            return []
        return [{"name": name} for name in resp.json().get("departments", [])]

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
        department: str,
        complaint: str | None = None,
        note: str | None = None,
        confirmed_by: str,
        rerouted: bool = False,
    ) -> bool:
        resp = await self._request(
            "PUT",
            f"/api/visits/{visit_id}/routing",
            json={
                "department": department,
                "complaint": complaint,
                "illness_note": note,
                "confirmed_by": confirmed_by,
                "rerouted": rerouted,
            },
        )
        if resp is None or resp.status_code != 200:
            logger.warning(
                "[HIS] confirm_routing visit=%s → %s",
                visit_id,
                None if resp is None else resp.status_code,
            )
            return False
        return True
