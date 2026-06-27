"""End-of-session disease keyword extraction for the outbreak surveillance dashboard.

Called when a session transitions to 'completed'. Uses Gemini to extract
structured symptom/disease keywords from the full user conversation, then
upserts the result into ``disease_surveillance``.

Guard conditions (all must pass before Gemini is called):
  1. Session has ≥ 2 user messages.
  2. At least 1 user message has meaningful health content (length > 10 chars,
     not just a greeting).
  3. The existing ``disease_surveillance`` row for this session has fewer than
     3 keywords — if routing rules already produced rich data, skip the extra
     API call.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import asyncpg

from app.config import settings
from app.services.ai.env import configure_google_genai_environment

configure_google_genai_environment()

logger = logging.getLogger(__name__)

# One-word / very-short messages that carry no health information.
_SKIP_PHRASES = {
    "hi", "hello", "hey", "ok", "okay", "yes", "no", "nope", "yep", "yeah",
    "thanks", "thank you", "bye", "goodbye", "sure", "alright", "fine",
    "good", "great", "done",
}

_MIN_USER_MESSAGES = 2
_MIN_MEANINGFUL_LENGTH = 10
_SKIP_IF_KEYWORDS_GTE = 3   # already have enough from routing rules

# Guard 2b: at least one message must contain a health signal word.
# Covers diseases, symptoms, body parts, and general illness vocabulary.
# Pure doctor/schedule queries ("is Dr. Smith available?") won't match any of these.
_HEALTH_SIGNALS = {
    # symptoms
    "pain", "ache", "hurt", "sore", "fever", "temperature", "cough",
    "sneeze", "runny", "congestion", "nausea", "vomit", "diarrhea",
    "constipation", "bleed", "bleeding", "dizzy", "dizziness", "faint",
    "fatigue", "tired", "weak", "weakness", "swollen", "swelling", "rash",
    "itch", "itchy", "burn", "burning", "numbness", "numb", "tingling",
    "shortness", "breathe", "breathing", "breath", "choke", "wheeze",
    "palpitation", "chest", "headache", "migraine", "cramp", "spasm",
    "discharge", "infection", "inflammation", "abscess",
    # diseases / conditions
    "covid", "corona", "flu", "influenza", "dengue", "malaria", "typhoid",
    "cholera", "tuberculosis", "pneumonia", "bronchitis", "asthma",
    "diabetes", "hypertension", "cancer", "tumor", "stroke", "seizure",
    "epilepsy", "anemia", "allergy", "appendicitis", "gastritis", "ulcer",
    "arthritis", "fracture", "sprain", "wound", "injury", "accident",
    # general illness words
    "sick", "ill", "unwell", "symptom", "condition", "diagnosis",
    "positive", "test", "tested", "smell", "taste", "vision", "hearing",
}

_EXTRACTION_PROMPT = """\
You are a medical keyword extractor for a hospital triage system.

Given the following patient messages from a chat session, extract a concise
list of disease names, symptoms, and body-part complaints that the patient
mentioned.

Rules:
- Return ONLY a valid JSON array of short keyword strings (1–3 words each).
- Use lowercase English.
- Include diseases (e.g. "covid", "dengue", "influenza"), symptoms
  (e.g. "fever", "sore throat", "muscle pain"), and body parts with problems
  (e.g. "ear pain", "chest pain").
- Do NOT include greetings, question phrases, or doctor/schedule queries.
- If no health keywords are found, return an empty array: []

Example output: ["fever", "sore throat", "covid", "loss of smell"]

Patient messages:
{messages}
"""


async def _call_gemini_extract(messages_text: str) -> list[str]:
    """Call Gemini with a simple text prompt and return parsed keyword list."""
    try:
        from google import genai as google_genai

        client = google_genai.Client()
        prompt = _EXTRACTION_PROMPT.format(messages=messages_text)

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.google_model_name,
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 256},
        )
        raw = (response.text or "").strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        keywords = json.loads(raw)
        if isinstance(keywords, list):
            return [str(k).strip().lower() for k in keywords if str(k).strip()]
    except Exception as exc:
        logger.warning("surveillance_extractor: gemini call failed: %s", exc)
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
    user_messages: list[dict[str, Any]] = [
        dict(r)
        for r in await connection.fetch(
            "SELECT content FROM messages WHERE session_id = $1 AND role = 'user' ORDER BY created_at",
            session_id,
        )
    ]

    if len(user_messages) < _MIN_USER_MESSAGES:
        logger.debug(
            "surveillance_extractor: skipped session %s — only %d user message(s)",
            session_id,
            len(user_messages),
        )
        return

    # ── Guard 2: at least one message has real health content ──────────────
    meaningful = [
        m["content"]
        for m in user_messages
        if (
            len(m["content"].strip()) > _MIN_MEANINGFUL_LENGTH
            and m["content"].strip().lower() not in _SKIP_PHRASES
        )
    ]

    if not meaningful:
        logger.debug(
            "surveillance_extractor: skipped session %s — no meaningful messages",
            session_id,
        )
        return

    # ── Guard 2b: at least one message contains a health signal word ──────
    # Filters out pure doctor/schedule conversations ("Is Dr. Smith available?")
    # before spending an API call on Gemini.
    all_text = " ".join(meaningful).lower()
    has_health_signal = any(signal in all_text for signal in _HEALTH_SIGNALS)

    if not has_health_signal:
        logger.debug(
            "surveillance_extractor: skipped session %s — no health signal words found",
            session_id,
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

    # ── Call Gemini ────────────────────────────────────────────────────────
    messages_text = "\n".join(f"- {m}" for m in meaningful)
    extracted: list[str] = await _call_gemini_extract(messages_text)

    if not extracted:
        logger.debug(
            "surveillance_extractor: session %s — gemini returned no keywords",
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
