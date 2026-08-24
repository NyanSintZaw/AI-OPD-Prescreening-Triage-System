"""End-of-session disease keyword extraction for the outbreak surveillance dashboard.

Called when a session transitions to 'completed'. Asks the screening model
(same adapter + provider switch as the engine, so on-prem it is the local
LLM) for symptom/disease keywords, then upserts the result into
``disease_surveillance``.

What is sent to the model is NOT the transcript: it is the screening state
the engine already extracted — chief complaint, present findings with their
values, OLDCARTS slot answers. That is the clinical content of the
conversation with none of the greeting / name / identity talk. The raw
``messages`` rows are only read locally for the guards below.
(ponytail: if recall on symptoms no criteria finding covers ever matters,
the raw-transcript input can return behind a flag.)

Guard conditions (all must pass before the model is called):
  1. Session has ≥ 2 user messages (counted locally, content never read).
  2. The existing ``disease_surveillance`` row for this session has fewer than
     3 keywords — if routing rules already produced rich data, skip the call.
  3. The engine's screening state exists and holds a complaint or findings.
     (The old guard was an English keyword list over the transcript, which
     silently skipped every Thai session.)
"""

from __future__ import annotations

import asyncio
import json
import logging

import asyncpg
from pydantic import BaseModel, Field

from app.config import settings
from app.services.screening.model_adapter import build_chat_model
from app.services.screening.nodes.base import ainvoke_with_timeout
from app.services.screening.state import ScreeningState

logger = logging.getLogger(__name__)

_MIN_USER_MESSAGES = 2
_SKIP_IF_KEYWORDS_GTE = 3   # already have enough from routing rules

_EXTRACTION_PROMPT = """\
You are a medical keyword extractor for a hospital triage system.

Given the structured summary of a screening conversation below, extract a
concise list of disease names, symptoms, and body-part complaints that the
patient reported.

Rules:
- Return short keyword strings (1–3 words each).
- Use lowercase English.
- Include diseases (e.g. "covid", "dengue", "influenza"), symptoms
  (e.g. "fever", "sore throat", "muscle pain"), and body parts with problems
  (e.g. "ear pain", "chest pain").
- Do NOT include greetings, question phrases, or doctor/schedule queries.
- If no health keywords are found, return an empty list.

Screening summary:
{messages}
"""


class SurveillanceKeywords(BaseModel):
    keywords: list[str] = Field(default_factory=list)


def screening_summary_text(state: ScreeningState) -> str:
    """What the model sees: the engine's own extraction, never the transcript."""
    lines: list[str] = []
    if state.complaint_category:
        lines.append(f"- complaint category: {state.complaint_category}")
    if state.chief_complaint:
        lines.append(f"- chief complaint: {state.chief_complaint}")
    for fid, finding in state.findings.items():
        if finding.state == "present":
            lines.append(f"- {fid}" + (f": {finding.value}" if finding.value else ""))
    for slot, answer in state.slots.items():
        lines.append(f"- {slot}: {answer}")
    return "\n".join(lines)


async def _call_model_extract(summary_text: str) -> list[str]:
    """One structured call through the screening model adapter."""
    try:
        model = build_chat_model(settings).with_structured_output(SurveillanceKeywords)
        prompt = _EXTRACTION_PROMPT.format(messages=summary_text)
        result = await ainvoke_with_timeout(
            model, prompt, float(settings.screening_model_timeout_s)
        )
        keywords = getattr(result, "keywords", None) or []
        return [str(k).strip().lower() for k in keywords if str(k).strip()]
    except Exception as exc:
        logger.warning("surveillance_extractor: model call failed: %s", exc)
    return []


async def extract_and_save(
    *,
    connection: asyncpg.Connection,
    session_id: str,
) -> None:
    """Run guard checks then extract + upsert surveillance keywords.

    Designed to be fire-and-forget from the session-complete endpoint —
    errors are logged but never raised.
    """
    try:
        await _run(connection=connection, session_id=session_id)
    except Exception as exc:
        logger.warning(
            "surveillance_extractor: unexpected error for session %s: %s",
            session_id,
            exc,
        )


async def _run(
    *,
    connection: asyncpg.Connection,
    session_id: str,
) -> None:

    # ── Guard 1: enough user messages ─────────────────────────────────────
    user_message_count = await connection.fetchval(
        "SELECT count(*) FROM messages WHERE session_id = $1 AND role = 'user'",
        session_id,
    )
    if (user_message_count or 0) < _MIN_USER_MESSAGES:
        logger.debug(
            "surveillance_extractor: skipped session %s — only %s user message(s)",
            session_id,
            user_message_count,
        )
        return

    # ── Guard 3: skip if routing rules already produced rich keywords ──────
    existing_row = await connection.fetchrow(
        "SELECT symptom_keywords FROM disease_surveillance WHERE session_id = $1",
        session_id,
    )
    existing_keywords: list[str] = list(existing_row["symptom_keywords"] or []) if existing_row else []

    if len(existing_keywords) >= _SKIP_IF_KEYWORDS_GTE:
        logger.debug(
            "surveillance_extractor: skipped session %s — already has %d keyword(s) from routing rules",
            session_id,
            len(existing_keywords),
        )
        return

    # ── Call the model with the engine's structured state, not the transcript
    state_row = await connection.fetchrow(
        "SELECT state FROM screening_sessions WHERE session_id = $1",
        session_id,
    )
    if state_row is None:
        logger.debug("surveillance_extractor: skipped session %s — no screening state", session_id)
        return
    summary_text = screening_summary_text(ScreeningState.from_json(state_row["state"]))
    if not summary_text:
        return
    extracted: list[str] = await _call_model_extract(summary_text)

    if not extracted:
        logger.debug(
            "surveillance_extractor: session %s — model returned no keywords",
            session_id,
        )
        return

    # Merge with any existing routing-rule keywords (keep both, deduplicate)
    merged = list(existing_keywords)
    for kw in extracted:
        if kw not in merged:
            merged.append(kw)

    # Fetch location (may have been set by the chat UI location prompt)
    location_area = await connection.fetchval(
        "SELECT location_area FROM sessions WHERE id = $1",
        session_id,
    )

    await connection.execute(
        """
        INSERT INTO disease_surveillance
            (session_id, symptom_keywords, symptoms_summary,
             severity_level, location_area)
        VALUES ($1, $2, $3, NULL, $4)
        ON CONFLICT (session_id) DO UPDATE
            SET symptom_keywords = EXCLUDED.symptom_keywords,
                location_area    = COALESCE(EXCLUDED.location_area, disease_surveillance.location_area),
                reported_at      = NOW()
        """,
        session_id,
        merged,
        None,
        location_area,
    )

    logger.info(
        "surveillance_extractor: session %s → saved keywords %s (location=%s)",
        session_id,
        merged,
        location_area,
    )
