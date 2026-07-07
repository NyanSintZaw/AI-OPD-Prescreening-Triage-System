"""Slip code derived from a session id.

The patient's printed slip shows a short human-readable code; the nurse at
the destination department types it to pull up the session. Must match the
frontend derivation in ``PatientIdPass.tsx`` (``shortVisitId``) exactly.
"""

from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^a-zA-Z0-9]")


def slip_code_for(session_id: str) -> str:
    clean = _NON_ALNUM.sub("", session_id).upper()
    if len(clean) <= 8:
        return clean
    return f"MCH-{clean[:4]}-{clean[-4:]}"
