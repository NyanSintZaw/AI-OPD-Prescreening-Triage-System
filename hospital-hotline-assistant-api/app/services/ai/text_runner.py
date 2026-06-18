"""Text/SSE ADK runner for hotline triage."""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from app.services.ai.env import configure_google_genai_environment

configure_google_genai_environment()

from google.adk.runners import Runner  # noqa: E402
from google.genai import types as genai_types  # noqa: E402

from app.services.ai.agent_factory import (  # noqa: E402
    APP_NAME,
    _SESSION_SERVICE,
    build_contact_preference_agent,
    build_orchestrator,
    build_triage_agent,
)
from app.services.ai.live_events import _strip_meta_markers  # noqa: E402

logger = logging.getLogger(__name__)

class HotlineADKRunner:
    """Async facade around the ADK Runner for hotline turns.

    Owns the root Orchestrator agent and the shared in-memory session
    service. The :meth:`chat` method is the only entry point used by
    the FastAPI route — it injects the [MODE: ...] prefix, drives the
    ADK event loop, and returns the reply plus any tool-call outputs
    the agents produced this turn.
    """

    def __init__(self) -> None:
        triage_agent = build_triage_agent(include_contact_tool=True)
        contact_agent = build_contact_preference_agent()
        self._root_agent = build_orchestrator(triage_agent, contact_agent)
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
        format. Returns a dict with the assistant reply plus any
        classification dict produced by tool calls this turn.
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
                        if response_payload.get("contact_preference_recorded") is True:
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
        * ``{"type": "done", "reply": "...", "classification": {...},
          "contact": {}, "input_mode": "..."}`` — terminal event with
          the fully-assembled reply and tool outputs, ready for
          ``triage_service`` to persist and run the rule engine.

        Uses ADK's ``StreamingMode.SSE`` so the runner emits partial
        events as Gemini produces tokens, plus an aggregated final
        event per LLM call. With our multi-agent setup (Orchestrator
        → TriageAgent, which can fire multiple tool calls), one user
        turn can trigger 2–4 LLM calls
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
                        if response_payload.get("contact_preference_recorded") is True:
                            contact = dict(response_payload)

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
