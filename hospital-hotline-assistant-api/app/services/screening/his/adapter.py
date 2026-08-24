"""HIS integration adapter protocol.

The engine and services depend only on this protocol so the concrete
implementation (``MockHisAdapter`` for demos, ``HttpHisAdapter`` against
the real hospital HIS or ``hospital-his-mock``) can be swapped in via
config without touching call sites (SRS §5.1).

Identity model (Data Requirements V1, 2026-08-11): the patient enters
their **HN** at the booth — HNs are the only stable identity MFU issues
(foreigners get a brand-new HN each visit, so a VN can never be the key).
The VN, when the HIS knows an active visit for the HN, rides along as
``current_visit`` and is passed through to the two write-backs, which the
hospital still keys by visit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class PatientHistory:
    """HN-level history + last-known vitals, joined from the HIS's patient
    (master) record — carried across visits, unlike per-visit vitals.

    ``is_first_time`` mirrors the HIS's ``history_recorded_at IS NULL``:
    true means the booth should run the first-time-patient history intake
    before the symptom interview. Field names follow Data Requirements V1
    §1.3 (smoking and alcohol separate, ``post_surgeries``). The free-text
    fields are for chart/nurse display plus LLM-free keyword findings;
    nothing here feeds the rules engine directly.
    """

    is_first_time: bool
    smoking: str | None = None
    alcohol: str | None = None
    allergies: str | None = None
    chronic_conditions: str | None = None
    post_surgeries: str | None = None
    family_history: str | None = None
    recorded_at: str | None = None  # ISO timestamp the history was taken, HIS-side
    last_weight_kg: float | None = None
    last_height_cm: float | None = None
    vitals_measured_at: str | None = None  # ISO timestamp, HIS-side


@dataclass(frozen=True)
class CurrentVisit:
    """The HN's newest routable visit — VN passthrough for the write-backs.
    None on the ``PatientInfo`` when the HIS knows no open visit (screening
    still runs; the write-backs then send the HN alone)."""

    visit_id: str
    appointment: bool = False


@dataclass(frozen=True)
class PatientInfo:
    """Everything the booth learns from ``GET /patients/{hn}``: identity,
    the demographics the rules need (birthdate → age band, gender), the
    carried-forward history, and the visit passthrough."""

    hn: str
    patient_name: str | None = None
    birthdate: str | None = None          # ISO date "YYYY-MM-DD" from the HIS
    age_years: int | None = None          # computed from birthdate when available
    # Registered sex from the HN master record: "male" / "female", or None
    # when the HIS lacks it (the booth then asks; never inferred).
    gender: str | None = None
    patient_history: "PatientHistory | None" = None
    current_visit: "CurrentVisit | None" = None
    raw: dict[str, Any] | None = None

    @property
    def is_first_time(self) -> bool:
        """Single source of truth is the history block (F4): first-time iff
        the HIS has no recorded history for this HN."""
        return self.patient_history.is_first_time if self.patient_history else True


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
    async def validate_patient(self, hn: str) -> PatientInfo | None:
        """Resolve the HN the patient typed at the booth; None when unknown.

        On success returns demographics (birthdate → age, gender), the
        carried-forward history/last vitals, and the HN's current visit
        (VN passthrough) when the HIS knows one.
        """

    async def push_prescreen(self, prescreen: dict[str, Any]) -> bool:
        """Stage 1 (Data Requirements V1 §2.1/§4.3): mark the patient
        pre-screened and awaiting nurse confirmation — objective booth
        measurements only, never the AI's judgement."""

    async def push_patient_history(self, hn: str, history: dict[str, Any]) -> bool:
        """Persist first-time-patient history (smoking, alcohol, allergies,
        chronic conditions, post surgeries, family history) onto the HN
        master record, so it carries forward to future visits."""

    async def push_patient_gender(self, hn: str, gender: str) -> bool:
        """Fill the HN master record's gender with a booth-collected value
        ("male"/"female"). Like ``push_patient_history``, the HIS side only
        ever fills an empty value and never overwrites a recorded one.
        (Our extension — Data Requirements V1 carries no gender field.)"""

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
        """Stage 2 (Data Requirements V1 §2.2/§4.4): send the patient to a
        destination *department* once a nurse has confirmed (the hospital's
        ``POST /patient-assignments``). The hospital picks the actual
        service point itself — we never send a spid.

        ``visit_id`` is the passthrough VN when known; with only ``hn`` the
        HIS resolves the patient's active visit itself. ``request_id`` is
        the idempotency key — allocated at confirm time and stored, so a
        retry after a timeout cannot create a second queue row. The nurse's
        narrative travels in ``sbar``; our screening block (triage level,
        vitals with provenance, confirmer, source refs) in ``mfu_prescreen``.
        """
