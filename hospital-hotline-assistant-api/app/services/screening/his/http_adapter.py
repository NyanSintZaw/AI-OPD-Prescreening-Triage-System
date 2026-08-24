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

from .adapter import AssignmentResult, CurrentVisit, PatientHistory, PatientInfo

logger = logging.getLogger(__name__)

# The hospital's assignment endpoint. Their UAT/PROD base URLs are documented
# with the /api/v1 suffix already on them — configure HIS_BASE_URL WITHOUT it,
# the way the mock is mounted at http://localhost:8001.
# Every call we make to the hospital, per Data Requirements V1. The booth flow
# is HN-first: GET /visits/{visit_id} still exists HIS-side but nothing here
# calls it any more.
ASSIGNMENTS_PATH = "/api/v1/patient-assignments"
PATIENT_PATH = "/api/v1/patients/{hn}"
PATIENT_HISTORY_PATH = "/api/v1/patients/{hn}/history"
PATIENT_GENDER_PATH = "/api/v1/patients/{hn}/gender"
PRESCREENS_PATH = "/api/v1/patient-prescreens"

# The station identity the hospital assigns our booth, sent with a prescreen
# so their attendance trail shows where the measurements were taken.
BOOTH_LOCATION = {
    "id": "AI-BOOTH-01",
    "name": "AI Pre-Screening Booth",
    "department": "แผนก ผู้ป่วยนอก(หน่วยคัดกรอง)",
}


def his_auth_headers(api_key: str | None) -> dict[str, str]:
    """Auth headers for HIS calls. Sends both schemes so one config works
    everywhere: the real iMed API wants ``Authorization: Bearer``; the
    ``hospital-his-mock`` convention is ``X-API-Key``."""
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}", "X-API-Key": api_key}


def _parse_patient_history(patient: dict[str, Any] | None) -> PatientHistory | None:
    """Parse a ``GET /patients/{hn}`` payload's history + last-vitals blocks
    into a ``PatientHistory``. None when the HIS doesn't support/return
    HN-level data. Field names per Data Requirements V1 §1.3/§1.4 — note the
    hospital's own ``hight`` spelling (``height`` accepted as a fallback)."""
    if not patient:
        return None
    history = patient.get("history") or {}
    last_vitals = patient.get("last_vitals") or {}
    return PatientHistory(
        is_first_time=bool(patient.get("is_first_time", True)),
        smoking=history.get("smoking"),
        alcohol=history.get("alcohol"),
        allergies=history.get("allergies"),
        chronic_conditions=history.get("chronic_conditions"),
        post_surgeries=history.get("post_surgeries"),
        family_history=history.get("family_history"),
        recorded_at=history.get("recorded_at"),
        last_weight_kg=last_vitals.get("weight"),
        last_height_cm=last_vitals.get("hight", last_vitals.get("height")),
        vitals_measured_at=last_vitals.get("measured_at"),
    )


# session.metadata.vitals key → the wire name Data Requirements V1 uses.
_PDF_VITAL_KEYS = {
    "systolic": "systolic",
    "diastolic": "diastolic",
    "pulse_bpm": "pulse_bpm",
    "temperature": "temperature_c",
    "weight_kg": "weight_kg",
    "height_cm": "hight_cm",   # the hospital's spelling — verbatim from V1
}

# Per-vital provenance → the V1 enum (device | patient_input). HIS-sourced
# values have no place in that enum, so their keys simply carry no entry.
_PDF_SOURCE_VALUES = {
    "device": "device",
    "patient_input": "patient_input",
    "manual": "patient_input",
}


def pdf_vitals(metadata_vitals: dict[str, Any] | None) -> dict[str, Any]:
    """Project ``session.metadata.vitals`` onto the Data Requirements V1
    vitals object (§2.1/§4.3): allowlisted keys only, wire renames
    (``temperature``→``temperature_c``, ``height_cm``→``hight_cm``), the
    normalized per-vital ``sources`` map, and ``bmi`` computed at send time.

    An explicit allowlist because the metadata blob carries internal keys
    (``source``, ``recorded_at``, ``bp_recheck_pending``, ``spo2``…) that
    must never leak into a hospital payload.
    """
    v = metadata_vitals or {}
    out: dict[str, Any] = {}
    for meta_key, wire_key in _PDF_VITAL_KEYS.items():
        if v.get(meta_key) is not None:
            out[wire_key] = v[meta_key]
    sources = {}
    for meta_key, provenance in (v.get("sources") or {}).items():
        wire_key = _PDF_VITAL_KEYS.get(meta_key)
        wire_value = _PDF_SOURCE_VALUES.get(provenance)
        if wire_key and wire_key in out and wire_value:
            sources[wire_key] = wire_value
    if sources:
        out["sources"] = sources
    weight, height = v.get("weight_kg"), v.get("height_cm")
    try:
        if weight and height and float(height) > 0:
            out["bmi"] = round(float(weight) / (float(height) / 100) ** 2, 2)
    except (TypeError, ValueError):
        pass  # implausible values are already dropped upstream by check_vitals
    return out


def with_bmi(vitals: dict[str, Any]) -> dict[str, Any]:
    """Add ``bmi`` when we hold both a weight and a height.

    Derived at send time rather than stored: that way it can never disagree
    with the weight and height sitting beside it in the same payload — a
    stored BMI goes stale the moment either is re-measured or corrected.
    """
    out = dict(vitals)
    weight, height = out.get("weight_kg"), out.get("height_cm")
    try:
        if weight and height and float(height) > 0:
            out["bmi"] = round(float(weight) / (float(height) / 100) ** 2, 2)
    except (TypeError, ValueError):
        pass  # implausible values are already dropped upstream by check_vitals
    return out


# Spellings a real HIS may use for the registered sex. Anything not listed
# maps to None (unknown) — the safe direction: the booth asks, and no rule
# is ever skipped on a value we didn't recognize.
_GENDER_ALIASES = {
    "male": "male", "m": "male", "ชาย": "male", "ช": "male",
    "female": "female", "f": "female", "หญิง": "female", "ญ": "female",
}


def _normalize_gender(value: Any) -> str | None:
    return _GENDER_ALIASES.get(str(value or "").strip().lower())


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

    async def validate_patient(self, hn: str) -> PatientInfo | None:
        """Resolve the HN the patient typed at the booth — one read gives
        identity, the age band, gender, the carried-forward history and the
        current-visit passthrough (Data Requirements V1 §1.2–1.4)."""
        if not hn.strip():
            return None
        resp = await self._request("GET", PATIENT_PATH.format(hn=hn.strip()))
        if resp is None or resp.status_code == 404:
            return None
        if resp.status_code != 200:
            logger.warning("[HIS] validate_patient %s → %s", hn, resp.status_code)
            return None
        data = resp.json()
        birthdate = data.get("birthdate")
        cv = data.get("current_visit") or None
        return PatientInfo(
            hn=data.get("hn") or hn.strip(),
            patient_name=data.get("patient_name"),
            birthdate=birthdate,
            age_years=_age_from_birthdate(birthdate),
            gender=_normalize_gender(data.get("gender")),
            patient_history=_parse_patient_history(data),
            current_visit=CurrentVisit(
                visit_id=str(cv["visit_id"]),
                appointment=bool(cv.get("appointment")),
            )
            if cv and cv.get("visit_id")
            else None,
            raw=data,
        )

    async def push_prescreen(self, prescreen: dict[str, Any]) -> bool:
        """Mark the patient pre-screened and awaiting nurse confirmation
        (Data Requirements V1 §2.1/§4.3).

        **Objective data only.** The recommended department, the complaint
        summary and the AI's reasoning are deliberately dropped here — they
        travel later, inside the SBAR of the assignment, once a nurse has
        signed them off. Sending them now would put unreviewed machine
        judgement in the hospital's record and make the confirm step
        decorative.
        """
        hn = prescreen.get("hn")
        if not hn:
            return False
        vitals = prescreen.get("vitals") or {}
        body = {
            # VN passthrough when the HIS gave us one at link time; with only
            # the HN the HIS resolves the patient's active visit itself.
            "visit_id": prescreen.get("visit_id"),
            "hn": hn,
            "session_ref": prescreen.get("session_ref"),
            "slip_code": prescreen.get("slip_code"),
            # Their export's own model: the booth is the FIRST location the
            # patient was seen at; the assignment sets the second.
            "first_location": BOOTH_LOCATION,
            "measured_at": vitals.get("measured_at") or vitals.get("recorded_at"),
            "vitals": pdf_vitals(vitals),
        }
        resp = await self._request("POST", PRESCREENS_PATH, json=body)
        if resp is None or not resp.is_success:
            logger.warning(
                "[HIS] prescreen hn=%s → %s",
                hn,
                None if resp is None else resp.status_code,
            )
            return False
        try:
            return resp.json().get("status") == "STATUS_SUCCESS"
        except ValueError:
            return False

    async def push_patient_history(self, hn: str, history: dict[str, Any]) -> bool:
        resp = await self._request(
            "PUT", PATIENT_HISTORY_PATH.format(hn=hn), json=history
        )
        if resp is None or resp.status_code != 200:
            logger.warning(
                "[HIS] push_patient_history hn=%s → %s",
                hn,
                None if resp is None else resp.status_code,
            )
            return False
        return True

    async def push_patient_gender(self, hn: str, gender: str) -> bool:
        # Fill-only on the HIS side (never overwrites), so this needs no
        # client-side read-before-write.
        resp = await self._request(
            "PUT", PATIENT_GENDER_PATH.format(hn=hn), json={"gender": gender}
        )
        if resp is None or resp.status_code != 200:
            logger.warning(
                "[HIS] push_patient_gender hn=%s → %s",
                hn,
                None if resp is None else resp.status_code,
            )
            return False
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
        body: dict[str, Any] = {
            "request_id": request_id,
            "visit_id": visit_id,
            "hn": hn,
            # Department granularity only (Data Requirements V1 §2.2): the
            # hospital assigns the service point / room itself, so no spid,
            # no queue_number, no assign_eid.
            "base_department_id": base_department_id,
        }
        if sbar and any(v for v in sbar.values()):
            body["sbar"] = {k: v for k, v in sbar.items() if v}
        if mfu_prescreen:
            body["mfu_prescreen"] = mfu_prescreen

        resp = await self._request("POST", ASSIGNMENTS_PATH, json=body)
        if resp is None:
            # Transport error or timeout: the queue row MAY have been created.
            # Never report this as a failure — see AssignmentResult.
            logger.warning("[HIS] assignment hn=%s → no response", hn)
            return AssignmentResult(status="unknown", request_id=request_id)

        try:
            payload = resp.json()
        except ValueError:
            logger.warning("[HIS] assignment hn=%s → non-JSON body", hn)
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
