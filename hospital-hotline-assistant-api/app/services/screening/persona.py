"""The assistant's voice as data.

``persona_block(language)`` returns the persona paragraph that opens every
patient-facing prompt (question rendering, explanation). It comes from
``app/data/persona_default.json`` so the wording is edited in one place and
can later be swapped per tenant. It shapes HOW things are said — decisions
are made by the rules engine and never read this.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

PERSONA_PATH = Path(__file__).resolve().parents[2] / "data" / "persona_default.json"


@lru_cache(maxsize=1)
def _load() -> dict:
    with PERSONA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def persona_block(language: str) -> str:
    """One paragraph: role, style rules, forbidden topics — for ``language``
    (falls back to English for an unknown code)."""
    data = _load()
    p = data.get(language) or data["en"]
    if language == "th":
        forbidden = " ".join(p["forbidden"])
        style = " ".join(p["style"])
        return f"{p['role']} {style} ข้อห้ามเด็ดขาด: {forbidden}"
    forbidden = "; ".join(p["forbidden"])
    style = " ".join(p["style"])
    return f"{p['role']} {style} STRICT RULES: {forbidden}."
