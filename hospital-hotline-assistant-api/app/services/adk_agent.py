"""Google ADK triage brain for the hospital hotline.

Replaces the legacy ``google_ai.py`` direct-Gemini wrapper with a
multi-agent ADK setup: an Orchestrator delegates to a TriageAgent
for ER Five-Level classification, and to an EmergencyAgent for
secure contact collection on Level 1 / 2 cases.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import re
from typing import Any, AsyncIterator

from app.config import settings

# google-genai (used by ADK under the hood) reads these env vars at Client
# construction time to decide between Vertex AI and the public Gemini API.
# pydantic-settings loads our .env into the Settings object but does NOT
# push values into os.environ, so we mirror them here BEFORE importing any
# google.adk / google.genai modules. Otherwise the LlmAgent's lazily-built
# Client falls through to API-key mode and raises "No API key was provided".
if settings.google_genai_use_vertexai:
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
if settings.google_cloud_project:
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", settings.google_cloud_project)
if settings.google_cloud_location:
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", settings.google_cloud_location)
if settings.google_application_credentials:
    os.environ.setdefault(
        "GOOGLE_APPLICATION_CREDENTIALS", settings.google_application_credentials
    )

from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.adk.tools import FunctionTool  # noqa: E402
from google.genai import types as genai_types  # noqa: E402


# Defensive belt-and-suspenders: even with the prompt explicitly forbidding
# it, Gemini sometimes echoes the `[MODE: ...]` / `[LANG: ...]` / `[CALL_START]`
# markers we inject onto user messages. Strip any leading run of such
# bracketed stage directions (and surrounding whitespace) from agent
# replies before they reach the caller / TTS layer.
_META_PREFIX_TOKEN_RE = re.compile(
    r"^\s*\[\s*(?:MODE|LANG|CALL_START)\b[^\]]*\]\s*",
    re.IGNORECASE,
)


def _strip_meta_markers(reply: str) -> str:
    """Remove any leading ``[MODE: ...]`` / ``[LANG: ...]`` / ``[CALL_START]``
    markers the model may have echoed back from the user-message envelope.

    We only strip from the front (and only those three specific labels) so
    that legitimate caller-facing brackets in the middle of an answer
    (e.g. "[Bangkok General]") aren't touched.
    """

    if not reply:
        return reply
    while True:
        stripped = _META_PREFIX_TOKEN_RE.sub("", reply, count=1)
        if stripped == reply:
            break
        reply = stripped
    return reply.lstrip()


"""
INTERACTION MODES
-----------------
Both modes share the same triage workflow and ADK agents.

MODE: "voice"  (Hotline)
  - Frontend: record audio → POST /stt → get transcript → POST /sessions/{id}/chat with input_mode="voice"
  - Agent reply is short natural spoken sentences (1–2 per turn max)
  - Frontend: POST reply text to /tts → play audio to caller
  - Future upgrade: replace STT→chat→TTS roundtrip with Gemini Live API bidirectional streaming

MODE: "text"  (Web Chat)
  - Frontend: typed message → POST /sessions/{id}/chat with input_mode="text"
  - Agent reply is readable prose with light formatting (line breaks ok, no markdown headers)
  - No TTS/STT involved
"""


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SECTION B — Reference data
# ---------------------------------------------------------------------------

# ``app/services/adk_agent.py`` -> parent (services) -> parent (app) -> "data"
DATA_DIR: pathlib.Path = pathlib.Path(__file__).parent.parent / "data"

_TRIAGE_FILE = DATA_DIR / "er_triage_five_level_system.json"
_DEPARTMENTS_FILE = DATA_DIR / "departments.json"


def _load_triage_reference() -> dict[str, Any]:
    """Load the ER Five-Level Triage JSON once at module import.

    Failure is fatal: without the decision tree the triage agent has
    nothing to reason against, so we'd rather crash on boot than
    serve incorrect classifications.
    """

    with _TRIAGE_FILE.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_departments() -> list[dict[str, Any]]:
    """Load the departments list once at module import.

    Falls back to a single Emergency entry if the file is missing or
    malformed -- the hotline must still be able to dispatch Level 1
    cases even when the catalogue is unavailable.
    """

    fallback: list[dict[str, Any]] = [
        {"code": "emergency", "name": "Emergency & Trauma"}
    ]
    try:
        with _DEPARTMENTS_FILE.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        departments = payload.get("departments")
        if isinstance(departments, list) and departments:
            return departments
        logger.warning(
            "departments.json missing 'departments' key or empty; using fallback"
        )
        return fallback
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        logger.warning("Could not load departments.json (%s); using fallback", exc)
        return fallback


_TRIAGE_REF: dict[str, Any] = _load_triage_reference()
_DEPARTMENTS: list[dict[str, Any]] = _load_departments()


# ---------------------------------------------------------------------------
# SECTION C — Function tools (mode-agnostic)
# ---------------------------------------------------------------------------


def get_triage_reference() -> dict:
    """Returns the complete ER Five-Level Triage system including decision_tree and
    triage_levels. ALWAYS call this before classifying. Follow decision_tree steps in order:
    Step 1 checks if dying (→Level 1). Step 2 checks high-risk/confused/severe pain (→Level 2).
    Step 3 checks resource count (none→Level 5, one→Level 4, many→proceed to Step 4).
    Step 4 checks danger zone vitals — if yes upgrade to Level 2, if no assign Level 3."""

    return _TRIAGE_REF


def get_department_list() -> list:
    """Returns available hospital departments. Use the exact department code
    (not name) in classify_triage_level.

    OPD-first policy:
    - Level 1–2 must use 'emergency'
    - Level 3–5 must use an 'opd_*' department code
    """

    return _DEPARTMENTS


def classify_triage_level(
    symptoms_summary: str,
    level: int,
    color: str,
    label: str,
    key_reason: str,
    department_code: str,
    response_time: str,
    needs_emergency_contact: bool,
) -> dict:
    """Record the final triage classification. Only call after consulting
    get_triage_reference and following the decision_tree. Set needs_emergency_contact=True
    for Level 1 and Level 2. For Level 1: classify immediately without follow-ups.
    For Level 2: allow at most 1 follow-up question before classifying.

    Department policy:
    - Level 1-2: department_code must be 'emergency'
    - Level 3-5: department_code must be an OPD code (prefix 'opd_')
    """

    return {
        "classified": True,
        "level": level,
        "color": color,
        "label": label,
        "key_reason": key_reason,
        "department_code": department_code,
        "response_time": response_time,
        "needs_emergency_contact": needs_emergency_contact,
        "symptoms_summary": symptoms_summary,
    }


def collect_emergency_contact(
    patient_name: str,
    phone_number: str,
    address: str,
) -> dict:
    """Collect patient contact for ambulance dispatch. Only call this AFTER
    classify_triage_level has been called with needs_emergency_contact=True."""

    return {
        "contact_collected": True,
        "patient_name": patient_name,
        "phone_number": phone_number,
        "address": address,
    }


# ---------------------------------------------------------------------------
# SECTION D — Agent system prompts
# ---------------------------------------------------------------------------

# Mode behaviour is NOT hardcoded into the instruction. The runtime
# prepends a "[MODE: voice|text ...]" line onto each user message,
# and the agent reads it from the REPLY FORMAT section below.


_TRIAGE_INSTRUCTION = """\
You are the Hospital Hotline Triage Assistant. You speak with the warm, calm,
professional tone of an experienced ER triage nurse. Patients calling you may
be anxious, in pain, or describing a family emergency — keep them grounded.

WORKFLOW
--------
1. Greet the caller briefly and ask what symptoms they (or the patient) are
   experiencing.
2. As soon as you receive any symptom information, call `get_triage_reference`
   so you can reason against the ESI Five-Level decision tree.
3. Walk the decision tree in order — Step 1 → Step 2 → Step 3 → Step 4.
   - Step 1: Is the patient dying / needs immediate life-saving intervention?
     If yes → Level 1.
   - Step 2: High-risk situation, confused / lethargic / disoriented, or in
     severe pain or distress? If yes → Level 2.
   - Step 3: How many different resources are needed? none → Level 5,
     one → Level 4, many → proceed to Step 4.
   - Step 4: Are danger-zone vitals present? Yes → upgrade to Level 2.
     No → Level 3.
4. If important information is missing, ask ONE focused follow-up question
   per turn until a triage can be identified. The exact number of
   follow-ups required depends on the apparent acuity of the case:
   - Level 1 (Red / Immediate, e.g. cardiac arrest, unresponsive, severe
     trauma): NO follow-ups. Classify immediately and reassure the
     caller that emergency help is being dispatched.
   - Level 2 (Orange / Emergent, e.g. active chest pain, signs of
     stroke, severe pain, suicidal): at most 1 focused follow-up
     before classifying.
   - Level 3 / 4 / 5 (anything that does NOT immediately match the
     Level 1 or Level 2 examples in the reference): ask AT LEAST 2–3
     targeted clarifying questions BEFORE classifying. A single
     symptom (e.g. just "I have a cough", "I have a headache",
     "my stomach hurts") is NOT enough to pick a level — you need to
     understand duration, severity, associated symptoms, vital sign
     red flags (fever, breathing difficulty, dizziness, vomiting,
     etc.), and any pre-existing conditions. Ask one question per
     turn, briefly, in a calm tone. Only call `classify_triage_level`
     once you have a plausible picture of the patient's situation.
   - Never classify on the very first turn unless the message itself
     contains an obvious Level 1 or Level 2 trigger from the
     reference's `examples` list.
5. Call `get_department_list` to confirm the correct department code before
   classifying.
6. Enforce MFU OPD-first policy when assigning department_code:
   - Level 1-2 must be `emergency`.
   - Level 3-5 must be one of the OPD codes returned by `get_department_list`
     (the code starts with `opd_`).
   - Never route Level 3-5 straight to emergency unless the case truly meets
     Level 1-2 criteria.
7. Call `classify_triage_level` with the final decision. For Level 1 and
   Level 2 always set `needs_emergency_contact=True`.
8. After classification, tell the patient their triage level + color + label,
   and the recommended OPD destination (or emergency department for Level 1-2),
   with estimated response time.
9. For Level 1 or Level 2, end your reply with ONE explicit prompt asking
   for all three contact fields by name so the caller knows exactly what to
   send next. Use a sentence like:
     English: "Please share your name, phone number, and address so we can
              dispatch help right away."
     Thai:    "ขอชื่อ หมายเลขโทรศัพท์ และที่อยู่ของคุณด้วยค่ะ
              เพื่อให้เราส่งความช่วยเหลือไปได้ทันที"
   Do NOT collect the contact details yourself — your only job here is to
   announce that the three pieces are needed. Another specialist
   (EmergencyAgent) takes the caller's next message and actually files the
   contact for dispatch.

LANGUAGE
--------
Every user message carries a `[LANG: en|th]` directive on its own line.
That code is the session language and it is LOCKED — you must reply
EXCLUSIVELY in that language for every turn. If `[LANG: en]` you write
English only; if `[LANG: th]` you write Thai only. Do not switch even if
the caller writes in the other language (e.g. an English session where
the caller types a Thai place name); stay in the locked language.
Never mix languages within a single reply.

REPLY FORMAT
------------
Check the [MODE:] prefix in each user message.
- [MODE: voice]: Maximum 1–2 short natural spoken sentences per turn.
  No bullet points, no markdown, no lists, no emoji.
- [MODE: text]: Clear readable prose. May use line breaks between thoughts.
  No markdown headers, no heavy formatting.

CRITICAL — DO NOT ECHO META MARKERS
-----------------------------------
The `[MODE: ...]` and `[LANG: ...]` lines on user messages are INSTRUCTIONS
addressed to you, not content you should repeat. Your reply must NEVER
begin with (or contain anywhere) any text that looks like `[MODE: ...]`,
`[LANG: ...]`, `[CALL_START]`, square-bracketed labels, or stage
directions. Start directly with what you want to say to the caller, in
plain natural language. If you ever feel inclined to write `[MODE:`,
stop — the caller never sees those markers and including them breaks
the user interface.
"""


_EMERGENCY_INSTRUCTION = """\
You are the Hospital Hotline Emergency Contact Collector. Triage already
identified a Level 1 or Level 2 case and asked the caller for three pieces
of information: the patient's name, their phone number, and their address.
Your single job is to extract those three values from the conversation and
file them via the `collect_emergency_contact` tool so an ambulance can be
dispatched.

EXTRACTION
----------
Scan the latest user message AND the prior conversation history for the
three fields. The caller may volunteer all three in one message
("I'm John, 555-1234, 123 Main St"), spread them across several messages,
or omit some. Accept any natural phrasing — labelled ("name: John") or
unlabelled ("John, 555-1234, 123 Main"). Phone numbers may include dashes,
spaces, or country codes — preserve them as-is.

CRITICAL — TOOL CALL IS MANDATORY
---------------------------------
The MOMENT you have values for ALL three fields (patient_name, phone_number,
address) — whether they arrived together in one message or were assembled
across multiple turns — you MUST call
`collect_emergency_contact(patient_name=..., phone_number=..., address=...)`
BEFORE writing your reply text. This is non-negotiable.

Never write "we have collected your information", "emergency services are
on their way", or any equivalent reassurance text without first invoking
`collect_emergency_contact`. If you produce that text without calling the
tool, the dispatch system never fires the alert and the ambulance is never
sent — a silent failure with potentially fatal consequences.

PARTIAL INFO
------------
If one or two fields are still missing after extraction, ask ONLY for the
missing ones in a single short message — never re-ask for fields the caller
already gave you. Examples (the <ALL_CAPS> markers are placeholders for the
actual value, not literal text — substitute them yourself):
- Only address missing → "Thanks. Could you share your address as well?"
- Phone + address missing → "Thanks <NAME>. What's your phone number and
  address?"
- Thai equivalents: "ขอบคุณค่ะ ขอ<ที่อยู่ / หมายเลขโทรศัพท์ / ...> ด้วยค่ะ"

AFTER THE TOOL CALL
-------------------
Reply with a brief reassurance using the values you just submitted (again,
the <ALL_CAPS> markers are placeholders — substitute the actual values):
"Thank you, <NAME>. Emergency services are on their way to <ADDRESS>. Your
callback number is <PHONE>." Translate naturally for Thai.

TONE / LANGUAGE / FORMAT
------------------------
Calm, warm, brief. Urgency overrides verbosity. Every user message carries
a `[LANG: en|th]` directive — that code is the session language and it is
LOCKED. Reply EXCLUSIVELY in that language even when the caller's own
message contains other-language tokens (e.g. a Thai-script address in an
English session — keep your reply in English). Never mix languages in one
reply. One or two short sentences per turn is ideal regardless of the
[MODE:] prefix.

CRITICAL — DO NOT ECHO META MARKERS
-----------------------------------
The `[MODE: ...]` and `[LANG: ...]` lines on user messages are INSTRUCTIONS
addressed to you. Your reply must NEVER contain `[MODE: ...]`,
`[LANG: ...]`, `[CALL_START]`, or any other square-bracketed stage
direction. Begin directly with what you want to say to the caller.
"""


_ORCHESTRATOR_INSTRUCTION = """\
You are the Hospital Hotline Orchestrator. Your ONLY job is to call
`transfer_to_agent` to route every turn to the correct specialist sub-agent.
You NEVER produce reply text yourself — the caller only ever sees the
sub-agent's reply.

ROUTING RULES (evaluate from top to bottom — first match wins)
--------------------------------------------------------------
1. If `EmergencyAgent` has already called `collect_emergency_contact` in
   this conversation (a tool response with `contact_collected: true` exists
   in history) → call `transfer_to_agent(agent_name="TriageAgent")` so the
   triage specialist can answer any further questions.

2. If `TriageAgent` has called `classify_triage_level` with
   `needs_emergency_contact=True` (Level 1 or Level 2) in this conversation
   AND `EmergencyAgent` has NOT yet called `collect_emergency_contact` →
   call `transfer_to_agent(agent_name="EmergencyAgent")`. Do this even if
   the current user message looks unrelated; contact collection is the only
   thing that matters until those three fields are in.

3. Default (new caller, still gathering symptoms, or non-emergency cases) →
   call `transfer_to_agent(agent_name="TriageAgent")`.

Always call `transfer_to_agent`. Never write text directly.
"""


# ---------------------------------------------------------------------------
# SECTION E — ADK wiring
# ---------------------------------------------------------------------------

APP_NAME: str = "hospital-hotline"

# Single in-memory session store shared by every Runner instance in this
# process. Demo-grade: state lives until the process restarts. Swap for a
# persistent SessionService (e.g. DatabaseSessionService) for production.
_SESSION_SERVICE: InMemorySessionService = InMemorySessionService()


def _build_triage_agent(model_name: str | None = None) -> LlmAgent:
    # ``model_name`` is optional so existing callers (HotlineADKRunner) keep
    # binding to ``settings.google_model_name`` (Pro tier, text). The live
    # runner passes ``settings.google_live_model_name`` because the Live API
    # only accepts its own dedicated model family.
    return LlmAgent(
        name="TriageAgent",
        description=(
            "Performs ER Five-Level triage classification. Asks targeted "
            "follow-up questions, consults the decision tree, then records "
            "the final level + department via classify_triage_level."
        ),
        model=model_name or settings.google_model_name,
        instruction=_TRIAGE_INSTRUCTION,
        tools=[
            FunctionTool(get_triage_reference),
            FunctionTool(get_department_list),
            FunctionTool(classify_triage_level),
        ],
    )


def _build_emergency_agent(model_name: str | None = None) -> LlmAgent:
    return LlmAgent(
        name="EmergencyAgent",
        description=(
            "Collects patient name, phone, and address for Level 1 / Level 2 "
            "ambulance dispatch. Activated only after the TriageAgent has "
            "classified the case with needs_emergency_contact=True."
        ),
        model=model_name or settings.google_model_name,
        instruction=_EMERGENCY_INSTRUCTION,
        tools=[FunctionTool(collect_emergency_contact)],
    )


def _build_orchestrator(
    triage_agent: LlmAgent,
    emergency_agent: LlmAgent,
    model_name: str | None = None,
) -> LlmAgent:
    return LlmAgent(
        name="HotlineOrchestrator",
        description=(
            "Routes hotline turns between the TriageAgent (symptom triage) "
            "and the EmergencyAgent (contact collection for dispatch)."
        ),
        model=model_name or settings.google_model_name,
        instruction=_ORCHESTRATOR_INSTRUCTION,
        sub_agents=[triage_agent, emergency_agent],
    )


# ---------------------------------------------------------------------------
# SECTION F — HotlineADKRunner
# ---------------------------------------------------------------------------


class HotlineADKRunner:
    """Async facade around the ADK Runner for hotline turns.

    Owns the root Orchestrator agent and the shared in-memory session
    service. The :meth:`chat` method is the only entry point used by
    the FastAPI route — it injects the [MODE: ...] prefix, drives the
    ADK event loop, and returns the reply plus any tool-call outputs
    the agents produced this turn.
    """

    def __init__(self) -> None:
        triage_agent = _build_triage_agent()
        emergency_agent = _build_emergency_agent()
        self._root_agent: LlmAgent = _build_orchestrator(
            triage_agent, emergency_agent
        )
        self._runner: Runner = Runner(
            app_name=APP_NAME,
            agent=self._root_agent,
            session_service=_SESSION_SERVICE,
        )

    async def ensure_adk_session(
        self, session_id: str, language: str, input_mode: str
    ) -> None:
        """Idempotently materialise the ADK session for ``session_id``.

        Uses ``session_id`` as both the ADK user_id and session_id so
        the hotline session UUID maps 1:1 onto ADK state. State seeds
        with the caller's language and the current input mode so any
        future agent can read them without re-parsing the prefix.
        """

        existing = await _SESSION_SERVICE.get_session(
            app_name=APP_NAME,
            user_id=session_id,
            session_id=session_id,
        )
        if existing is not None:
            return

        await _SESSION_SERVICE.create_session(
            app_name=APP_NAME,
            user_id=session_id,
            session_id=session_id,
            state={
                "language": language,
                "session_id": session_id,
                "input_mode": input_mode,
            },
        )

    async def chat(
        self,
        session_id: str,
        language: str,
        user_message: str,
        input_mode: str,
    ) -> dict[str, Any]:
        """Run one hotline turn through the ADK Orchestrator.

        See module docstring for how ``input_mode`` shapes the reply
        format. Returns a dict with the assistant reply plus the
        classification / contact dicts produced by tool calls this
        turn (each ``{}`` if the corresponding tool was not invoked).
        """

        # Step 1 — make sure the ADK session exists.
        await self.ensure_adk_session(session_id, language, input_mode)

        # Step 2 — prepend the mode + language prefix so the agents render
        # the right reply format AND stay strictly inside the session's
        # language. The language is locked at session creation and must
        # never drift even if the caller writes in a different language
        # this turn (e.g. an English session getting Thai place names in
        # a contact reply).
        lang_code = language if language in {"en", "th"} else "en"
        lang_name = "English" if lang_code == "en" else "Thai"
        if input_mode == "voice":
            mode_line = (
                "[MODE: voice — reply in short spoken sentences, no formatting]"
            )
        else:
            mode_line = (
                "[MODE: text — reply in clear readable prose, light formatting ok]"
            )
        lang_line = (
            f"[LANG: {lang_code} — reply EXCLUSIVELY in {lang_name}. "
            f"This is the session language and it does not change. Even if "
            f"the caller writes in another language this turn, your reply "
            f"MUST be in {lang_name}.]"
        )
        final_content = f"{mode_line}\n{lang_line}\n{user_message}"

        # Step 3 — wrap the message in the ADK Content envelope.
        content = genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=final_content)],
        )

        # Step 4 — drive the runner event loop, collecting reply text
        # from final-response events and scanning *every* event for
        # tool-call outputs.
        reply_chunks: list[str] = []
        classification: dict[str, Any] = {}
        contact: dict[str, Any] = {}

        try:
            async for event in self._runner.run_async(
                user_id=session_id,
                session_id=session_id,
                new_message=content,
            ):
                event_content = getattr(event, "content", None)
                parts = getattr(event_content, "parts", None) or []

                is_final = False
                try:
                    is_final = event.is_final_response()
                except Exception:  # noqa: BLE001 - defensive against ADK shape drift
                    is_final = False

                for part in parts:
                    # Text → only counted toward the reply when it's a
                    # final response event. Intermediate "thinking"
                    # text would otherwise leak into the caller.
                    if is_final:
                        text = getattr(part, "text", None)
                        if text:
                            reply_chunks.append(text)

                    # Tool outputs → scan every event regardless of
                    # final-ness, since the function_response event
                    # is emitted before the agent's final wrap-up.
                    func_response = getattr(part, "function_response", None)
                    response_payload = (
                        getattr(func_response, "response", None)
                        if func_response is not None
                        else None
                    )
                    if isinstance(response_payload, dict):
                        if response_payload.get("classified") is True:
                            classification = dict(response_payload)
                        if response_payload.get("contact_collected") is True:
                            contact = dict(response_payload)
        except Exception:
            logger.exception(
                "ADK runner failed for session=%s mode=%s", session_id, input_mode
            )
            # Fall through with empty reply so the fallback below kicks in.

        reply = _strip_meta_markers("".join(reply_chunks).strip())

        # Step 5 — language- and mode-aware fallback when the agent
        # produced no text (e.g. delegated indefinitely, model error,
        # safety filter). Default to English for any unknown lang.
        if not reply:
            lang = language if language in {"en", "th"} else "en"
            fallbacks: dict[tuple[str, str], str] = {
                ("voice", "en"): "I'm sorry, could you describe your symptoms?",
                ("voice", "th"): "ขอโทษนะคะ ช่วยบอกอาการของคุณได้ไหมคะ",
                ("text", "en"): (
                    "Please describe your symptoms so I can assess your situation."
                ),
                ("text", "th"): (
                    "กรุณาบอกอาการของคุณ เพื่อให้เราช่วยประเมินสถานการณ์ได้"
                ),
            }
            mode_key = "voice" if input_mode == "voice" else "text"
            reply = fallbacks[(mode_key, lang)]

        # Step 6 — return the structured turn result.
        return {
            "reply": reply,
            "classification": classification,
            "contact": contact,
            "input_mode": input_mode,
        }

    async def chat_stream(
        self,
        session_id: str,
        language: str,
        user_message: str,
        input_mode: str,
    ) -> "AsyncIterator[dict[str, Any]]":
        """Streaming variant of :meth:`chat`.

        Yields a sequence of small event dicts as the agent generates,
        designed to be relayed to the frontend as Server-Sent Events.
        Event shapes (all carry a ``type`` field):

        * ``{"type": "delta", "text": "..."}`` — a partial text fragment
          from the ongoing model response. Frontend appends these to a
          live assistant bubble.
        * ``{"type": "reset"}`` — a previously-streamed chunk turned
          out to be pre-tool-call thinking from one of the inner LLM
          calls (Orchestrator routing, agent reasoning before a tool
          dispatch). Frontend should wipe the assistant bubble and the
          TTS queue, then resume appending future deltas.
        * ``{"type": "classified", "classification": {...}}`` — fired
          the moment the agent invokes ``classify_triage_level``. The
          payload mirrors what the tool returned.
        * ``{"type": "contact", "contact": {...}}`` — fired when the
          EmergencyAgent submits ``collect_emergency_contact``.
        * ``{"type": "done", "reply": "...", "classification": {...},
          "contact": {...}, "input_mode": "..."}`` — terminal event with
          the fully-assembled reply and tool outputs, ready for
          ``triage_service`` to persist and run the rule engine /
          notifier pipeline against.

        Uses ADK's ``StreamingMode.SSE`` so the runner emits partial
        events as Gemini produces tokens, plus an aggregated final
        event per LLM call. With our multi-agent setup (Orchestrator
        → TriageAgent / EmergencyAgent, each of which can fire
        multiple tool calls), one user turn can trigger 2–4 LLM calls
        — and Gemini's 2.5 family likes to emit reasoning text
        *alongside* every function_call it makes. If we naively
        forwarded all partial text the caller would see 3–4
        paraphrased greetings stitched together.

        The dedupe rule: stream partials as deltas, but when a
        non-partial aggregated event arrives, inspect its content. If
        that LLM call ended in a ``function_call`` / ``transfer_to_agent``,
        the deltas we just streamed were *pre-tool-call thinking* —
        emit a ``reset`` so the frontend (and TTS queue) wipes the
        bubble and starts fresh on the next LLM call's partials. Only
        the final LLM call (text-only aggregated event) survives.
        """

        from google.adk.agents.run_config import (  # local import — load cost
            RunConfig,
            StreamingMode,
        )

        await self.ensure_adk_session(session_id, language, input_mode)

        lang_code = language if language in {"en", "th"} else "en"
        lang_name = "English" if lang_code == "en" else "Thai"
        if input_mode == "voice":
            mode_line = (
                "[MODE: voice — reply in short spoken sentences, no formatting]"
            )
        else:
            mode_line = (
                "[MODE: text — reply in clear readable prose, light formatting ok]"
            )
        lang_line = (
            f"[LANG: {lang_code} — reply EXCLUSIVELY in {lang_name}. "
            f"This is the session language and it does not change. Even if "
            f"the caller writes in another language this turn, your reply "
            f"MUST be in {lang_name}.]"
        )
        final_content = f"{mode_line}\n{lang_line}\n{user_message}"

        content = genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=final_content)],
        )

        run_config = RunConfig(streaming_mode=StreamingMode.SSE)

        # The text in ``current_run_chunks`` belongs to the LLM call
        # whose aggregated event hasn't arrived yet. If that aggregated
        # event ends in a function_call we discard the chunks (and ask
        # the frontend to reset). If it ends in just text we keep them
        # as the canonical reply so far.
        kept_chunks: list[str] = []
        current_run_chunks: list[str] = []
        classification: dict[str, Any] = {}
        contact: dict[str, Any] = {}

        # Tracks whether we've already stripped the meta-marker prefix
        # from the streaming output. The model occasionally echoes
        # ``[MODE: text][LANG: en]`` at the very start of its first
        # streamed chunk; we only need to clean the leading bytes once.
        prefix_cleaned = False

        try:
            async for event in self._runner.run_async(
                user_id=session_id,
                session_id=session_id,
                new_message=content,
                run_config=run_config,
            ):
                event_content = getattr(event, "content", None)
                parts = getattr(event_content, "parts", None) or []
                is_partial = bool(getattr(event, "partial", False))

                # Inspect this event for tool-call / tool-response
                # signals BEFORE handling text. ``has_function_call``
                # tells us this LLM call ended in a tool dispatch
                # (so its text was reasoning, not the final reply).
                has_function_call = any(
                    getattr(p, "function_call", None) is not None for p in parts
                )

                for part in parts:
                    func_response = getattr(part, "function_response", None)
                    response_payload = (
                        getattr(func_response, "response", None)
                        if func_response is not None
                        else None
                    )
                    if isinstance(response_payload, dict):
                        if response_payload.get("classified") is True:
                            classification = dict(response_payload)
                            yield {
                                "type": "classified",
                                "classification": classification,
                            }
                        if response_payload.get("contact_collected") is True:
                            contact = dict(response_payload)
                            yield {"type": "contact", "contact": contact}

                if is_partial:
                    # Stream text deltas as they arrive. We can't yet
                    # tell whether this LLM call will end in a tool
                    # dispatch (thinking) or plain text (final reply),
                    # so we forward eagerly for the typewriter effect
                    # and reconcile on the aggregated event below.
                    for part in parts:
                        text = getattr(part, "text", None)
                        if not text:
                            continue
                        chunk = str(text)
                        if not prefix_cleaned:
                            chunk = _strip_meta_markers(chunk)
                            prefix_cleaned = True
                        if chunk:
                            current_run_chunks.append(chunk)
                            yield {"type": "delta", "text": chunk}
                    continue

                # Non-partial = aggregated event for this LLM call.
                # Decide whether to keep or discard the deltas we just
                # streamed.
                if has_function_call:
                    # Reasoning before a tool dispatch — wipe the bubble.
                    if current_run_chunks:
                        current_run_chunks = []
                        yield {"type": "reset"}
                else:
                    # Plain-text aggregated event → those deltas were
                    # real reply content. Commit them.
                    kept_chunks.extend(current_run_chunks)
                    current_run_chunks = []
        except Exception:
            logger.exception(
                "ADK stream failed for session=%s mode=%s",
                session_id,
                input_mode,
            )
            # Fall through to fallback so the frontend still gets a
            # ``done`` event and the UI doesn't hang on an empty stream.

        # If the stream ended without a terminating aggregated event
        # (network hiccup, model finish_reason oddity, etc.) treat any
        # un-committed deltas as part of the reply so the user still
        # sees the text they already saw on screen.
        if current_run_chunks:
            kept_chunks.extend(current_run_chunks)
            current_run_chunks = []

        reply = _strip_meta_markers("".join(kept_chunks).strip())

        if not reply:
            lang = language if language in {"en", "th"} else "en"
            fallbacks: dict[tuple[str, str], str] = {
                ("voice", "en"): "I'm sorry, could you describe your symptoms?",
                ("voice", "th"): "ขอโทษนะคะ ช่วยบอกอาการของคุณได้ไหมคะ",
                ("text", "en"): (
                    "Please describe your symptoms so I can assess your situation."
                ),
                ("text", "th"): (
                    "กรุณาบอกอาการของคุณ เพื่อให้เราช่วยประเมินสถานการณ์ได้"
                ),
            }
            mode_key = "voice" if input_mode == "voice" else "text"
            reply = fallbacks[(mode_key, lang)]
            # Surface the fallback as a single delta so the client UI
            # still sees the bubble fill with text even when streaming
            # produced nothing.
            yield {"type": "delta", "text": reply}

        yield {
            "type": "done",
            "reply": reply,
            "classification": classification,
            "contact": contact,
            "input_mode": input_mode,
        }


# ---------------------------------------------------------------------------
# SECTION G — HotlineADKLiveRunner  (Gemini Live API bidirectional voice)
# ---------------------------------------------------------------------------
#
# In google-adk 2.1.0 there is no separate ``LiveRunner`` class — the regular
# ``Runner`` exposes ``run_live(...)`` for bidirectional streaming. We wrap a
# Runner that shares the SAME root agent + tool set + session service the
# text-mode runner uses, but lives under its own app_name so the live
# session state is isolated from the text-mode chat history.
#
# Voice selection is per-session (caller's language is known at connect
# time) and is supplied via ``RunConfig.speech_config``. Audio in/out
# transcription is also turned on so callers' speech becomes text we can
# feed back into ``triage_service.process_chat`` for DB persistence and
# mock-notifier dispatch.

LIVE_APP_NAME: str = "hospital-hotline-live"

# Gemini Live API prebuilt voice. We pin a SINGLE voice across every
# language for persona consistency — callers should hear the same
# "hotline nurse" voice on every call, whether they're speaking English
# or Thai. ``Aoede`` is the warm-female conversational voice and
# renders both languages cleanly under the native-audio model. Picking
# different voices per language (e.g. Aoede en / Charon th) made the
# assistant sound like two different people, which the demo brief
# explicitly called out.
_VOICE_NAME: str = "Aoede"

# BCP-47 language code we pin into the SpeechConfig so the upstream
# model routes through the correct voice variant deterministically.
# Without an explicit code Gemini Live infers one from the response
# stream, and we observed that inference flipping between calls
# (causing the "different voice every call" symptom). Pinning it
# locks the rendering to a single consistent voice per language.
_LANGUAGE_CODE_BY_LANG: dict[str, str] = {
    "en": "en-US",
    "th": "th-TH",
}


def _build_live_run_config(language: str) -> "genai_types.LiveConnectConfig | Any":
    """Assemble the ``RunConfig`` ADK passes into the Gemini Live API.

    Picks the prebuilt voice for the caller's language, enables audio-only
    responses, and turns on both input and output transcription so the
    service layer can replay the conversation into the existing text
    pipeline (which handles DB writes and emergency notifications).
    """

    from google.adk.runners import RunConfig  # local import to avoid load-time cost

    # Single voice across every language — see ``_VOICE_NAME`` docstring
    # for why we deliberately don't switch per locale. Coupling
    # ``voice_name`` with an explicit BCP-47 ``language_code`` locks the
    # Gemini Live API into the same voice variant on every connect, so
    # the assistant sounds like the same person every call.
    bcp47 = _LANGUAGE_CODE_BY_LANG.get(language, _LANGUAGE_CODE_BY_LANG["en"])
    speech_config = genai_types.SpeechConfig(
        voice_config=genai_types.VoiceConfig(
            prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                voice_name=_VOICE_NAME,
            ),
        ),
        language_code=bcp47,
    )

    # Pin BOTH transcription streams to the session's language so the
    # captions never cross-leak (caller speaks Thai → captions show
    # Thai only; English session → English captions only). Without an
    # explicit ``language_codes`` hint Gemini's transcriber
    # auto-detects per-utterance and frequently flips mid-call if the
    # caller's accent triggers a different language model. The hint
    # also improves accuracy for monolingual sessions because the
    # model can lean on the pinned language's lexicon instead of
    # hedging across candidates.
    transcription_config = genai_types.AudioTranscriptionConfig(
        language_codes=[bcp47],
    )
    return RunConfig(
        response_modalities=["AUDIO"],
        speech_config=speech_config,
        input_audio_transcription=transcription_config,
        output_audio_transcription=transcription_config,
    )


class HotlineADKLiveRunner:
    """Async facade around ADK's bidirectional live runner.

    Shares the same Orchestrator + sub-agents + tool set that
    :class:`HotlineADKRunner` uses, so a Level 1 / Level 2 classification
    in a voice call still fires ``classify_triage_level`` and triggers
    the EmergencyAgent handoff for contact collection. The only thing
    that differs from text mode is the runner's ``app_name`` (so ADK
    session state is namespaced separately) and the
    :meth:`run_live` entry point.
    """

    def __init__(self) -> None:
        # The Live API only accepts ``gemini-live-*-native-audio`` models, so
        # we override the agents' model here instead of the Pro-tier text
        # default. Reuses the same instructions / tools / sub-agent layout
        # as HotlineADKRunner — only the wire model changes.
        live_model = settings.google_live_model_name
        triage_agent = _build_triage_agent(model_name=live_model)
        emergency_agent = _build_emergency_agent(model_name=live_model)
        self._root_agent: LlmAgent = _build_orchestrator(
            triage_agent, emergency_agent, model_name=live_model
        )
        self._runner: Runner = Runner(
            app_name=LIVE_APP_NAME,
            agent=self._root_agent,
            session_service=_SESSION_SERVICE,
        )

    async def ensure_live_session(
        self, session_id: str, language: str
    ) -> None:
        """Idempotently materialise the live-mode ADK session.

        Mirrors :meth:`HotlineADKRunner.ensure_adk_session` but binds to
        the ``LIVE_APP_NAME`` namespace and pins ``input_mode`` to
        ``"voice"`` in initial state since this session is voice-only by
        definition.
        """

        existing = await _SESSION_SERVICE.get_session(
            app_name=LIVE_APP_NAME,
            user_id=session_id,
            session_id=session_id,
        )
        if existing is not None:
            return
        await _SESSION_SERVICE.create_session(
            app_name=LIVE_APP_NAME,
            user_id=session_id,
            session_id=session_id,
            state={
                "language": language,
                "session_id": session_id,
                "input_mode": "voice",
            },
        )

    async def get_live_session_handler(
        self, session_id: str, language: str
    ) -> Runner:
        """Make sure the ADK session is ready and return the underlying Runner.

        The caller drives the live pipeline by invoking ``runner.run_live(
        user_id=..., session_id=..., live_request_queue=..., run_config=...
        )``. The session must exist before ``run_live`` is called or ADK
        raises ``SessionNotFoundError``.
        """

        await self.ensure_live_session(session_id, language)
        return self._runner

    def build_run_config(self, language: str) -> Any:
        """Public wrapper around :func:`_build_live_run_config` so callers
        don't have to import the module-private helper.
        """

        return _build_live_run_config(language)
