"""HIS integration adapter protocol.

The engine and services depend only on this protocol so the concrete
implementation (``MockHisAdapter`` for demos, ``HttpHisAdapter`` against
the real hospital HIS or ``hospital-his-mock``) can be swapped in via
config without touching call sites (SRS §5.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class PatientHistory:
    """HN-level history + last-known vitals, joined from the HIS's patient
    (master) record — carried across visits, unlike per-visit vitals.

    ``is_first_time`` mirrors the HIS's ``history_recorded_at IS NULL``:
    true means the booth should run the first-time-patient history intake
    before the symptom interview. The free-text fields are for chart/nurse
    display only; nothing here feeds the rules engine directly yet (§5.5 of
    the backend/AI plan — future phase).
    """

    is_first_time: bool
    smoking_alcohol: str | None = None
    allergies: str | None = None
    chronic_conditions: str | None = None
    past_surgeries: str | None = None
    family_history: str | None = None
    recorded_at: str | None = None  # ISO timestamp the history was taken, HIS-side
    last_weight_kg: float | None = None
    last_height_cm: float | None = None
    vitals_measured_at: str | None = None  # ISO timestamp, HIS-side


@dataclass(frozen=True)
class VisitInfo:
    visit_id: str
    patient_id: str | None = None
    patient_name: str | None = None
    is_active: bool = True
    birthdate: str | None = None          # ISO date "YYYY-MM-DD" from the HIS
    age_years: int | None = None          # computed from birthdate when available
    vitals: dict[str, Any] = field(default_factory=dict)  # HIS-recorded vitals
    appointment: bool = False
    patient_history: "PatientHistory | None" = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class AssignmentResult:
    """Outcome of a Stage-2 patient assignment.

    ``status`` is written straight into ``session.metadata.his_routing`` and
    drives what the nurse is shown:

    * ``pushed``      queued — ``queue_number`` is what the nurse hands over.
                      A 409 "already exists" also lands here: our earlier
                      attempt succeeded.
    * ``denied``      403, the visit is locked/discharged. Do not retry.
    * ``unavailable`` 422, the destination is closed. The nurse reroutes.
    * ``invalid``     400 (or 2xx with a non-success body) — our bug.
    * ``unknown``     timeout/transport/5xx. The queue row **may** exist, so
                      this is deliberately NOT "failed": a retry reuses the
                      same ``request_id`` and cannot double-book.
    """

    status: str
    request_id: str
    queue_number: str | None = None
    visit_queue_id: str | None = None
    queue_status: str | None = None
    sbar_id: str | None = None
    assign_eid: str | None = None
    message: str | None = None       # iMed's enum — for logs/IT, not the nurse
    message_th: str | None = None    # what the nurse is shown
    http_status: int | None = None


class HisAdapter(Protocol):
    async def validate_visit(self, visit_id: str) -> VisitInfo | None:
        """Verify a visit id against the HIS; None when unknown/inactive.

        On success returns demographics (birthdate → age) and any vitals the
        HIS already holds, so the booth can pre-fill without asking.
        """

    async def get_departments(self) -> list[dict[str, Any]]:
        """Approved department names/locations from the HIS, when supported."""

    async def push_referral(self, referral: dict[str, Any]) -> bool:
        """Stage 1: send the AI booth's pending pre-screening referral to
        the HIS (recommended department, complaint, vitals, reasons)."""

    async def push_patient_history(self, hn: str, history: dict[str, Any]) -> bool:
        """Persist first-time-patient history (smoking/alcohol, allergies,
        chronic conditions, past surgeries, family history) onto the HN
        master record, so it carries forward to future visits."""

    async def push_follow_up(self, visit_id: str, follow_up: str) -> bool:
        """Record the patient's own follow-up question/concern on the visit
        so the destination doctor/nurse sees it. Verbatim patient words —
        needs no sign-off."""

    async def confirm_routing(
        self,
        visit_id: str,
        *,
        request_id: str,
        assign_spid: str,
        sbar: dict[str, str | None] | None = None,
    ) -> AssignmentResult:
        """Stage 2: send the visit to its destination service point once a
        nurse has confirmed (the hospital's ``POST /patient-assignments``).

        ``request_id`` is the idempotency key — allocated at confirm time and
        stored, so a retry after a timeout cannot create a second queue row.
        The nurse's chief complaint and illness note travel inside ``sbar``;
        who confirmed and whether it was a reroute stay in our own audit
        trail, because iMed derives the sender from the access token and has
        no reroute flag."""
