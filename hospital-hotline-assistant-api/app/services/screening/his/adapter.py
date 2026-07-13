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
class VisitInfo:
    visit_id: str
    patient_id: str | None = None
    patient_name: str | None = None
    is_active: bool = True
    birthdate: str | None = None          # ISO date "YYYY-MM-DD" from the HIS
    age_years: int | None = None          # computed from birthdate when available
    vitals: dict[str, Any] = field(default_factory=dict)  # HIS-recorded vitals
    appointment: bool = False
    raw: dict[str, Any] | None = None


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
        """Stage 2: record the nurse's confirmation or reroute at the
        destination department (updates the visit's second location).

        ``complaint``/``note`` are the nurse-signed chief complaint and
        illness note; None keeps the values held from Stage 1."""
