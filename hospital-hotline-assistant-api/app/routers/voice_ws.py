import asyncio
import json
import logging
import asyncpg
from fastapi import (
    WebSocket,
    WebSocketDisconnect,
)

logger = logging.getLogger(__name__)

from fastapi import APIRouter

router = APIRouter()

@router.websocket("/ws/voice/{session_id}")
async def voice_call(websocket: WebSocket, session_id: str):
    await websocket.accept()
    pool: asyncpg.Pool = websocket.app.state.db_pool
    live_voice_service = websocket.app.state.live_voice_service  # TurnVoiceService
    requested_language = websocket.query_params.get("language", "en")
    language = requested_language if requested_language in {"en", "th"} else "en"
    # Kiosk found a same-day session for this VN: open the call with the
    # spoken continue-vs-start-over gate ('active' | 'completed').
    raw_resume = websocket.query_params.get("resume_prompt")
    resume_prompt = raw_resume if raw_resume in {"active", "completed"} else None

    # Callbacks forward turn transcripts + emergency banner triggers to the
    # frontend over the WS. ``send_*`` may raise if the client closed the
    # socket mid-send; swallow those so a disconnect race doesn't crash the
    # pipeline.
    async def push_transcript(role: str, text: str) -> None:
        try:
            await websocket.send_json(
                {"type": "transcript", "role": role, "text": text}
            )
        except Exception:
            logger.debug(
                "Failed to push transcript to %s (likely client closed)",
                session_id,
            )

    async def push_emergency(payload: dict) -> None:
        try:
            await websocket.send_json({"type": "emergency", **payload})
        except Exception:
            logger.debug(
                "Failed to push emergency to %s (likely client closed)",
                session_id,
            )

    async def push_assessment(payload: dict) -> None:
        try:
            await websocket.send_json({"type": "assessment_complete", **payload})
        except Exception:
            logger.debug(
                "Failed to push assessment to %s (likely client closed)",
                session_id,
            )

    async def push_measurement(payload: dict) -> None:
        try:
            await websocket.send_json({"type": "measurement_request", **payload})
        except Exception:
            logger.debug(
                "Failed to push measurement request to %s (likely client closed)",
                session_id,
            )

    async def push_options(payload: dict) -> None:
        try:
            await websocket.send_json({"type": "question_options", **payload})
        except Exception:
            logger.debug(
                "Failed to push question options to %s (likely client closed)",
                session_id,
            )

    async def push_identity(payload: dict) -> None:
        # {"kind": "confirmed"|"rejected", "needs_history": bool} — the
        # spoken VN name-confirm outcome; the kiosk transitions on it.
        try:
            await websocket.send_json({"type": "identity", **payload})
        except Exception:
            logger.debug(
                "Failed to push identity outcome to %s (likely client closed)",
                session_id,
            )

    async def push_resume(payload: dict) -> None:
        # {"kind": "continue"|"start_over"|"decline", ...} — the spoken
        # continue-vs-start-over outcome; the kiosk transitions on it.
        try:
            await websocket.send_json({"type": "resume_choice", **payload})
        except Exception:
            logger.debug(
                "Failed to push resume outcome to %s (likely client closed)",
                session_id,
            )

    async def push_visemes(payload: dict) -> None:
        # Vowel timeline for the avatar's lip sync — arrives before the
        # spoken line's audio chunks so the client can anchor it.
        try:
            await websocket.send_json({"type": "viseme_track", **payload})
        except Exception:
            logger.debug(
                "Failed to push viseme track to %s (likely client closed)",
                session_id,
            )

    async with pool.acquire() as conn:
        try:
            await live_voice_service.connect(
                session_id,
                language,
                conn,
                db_pool=pool,
                transcript_callback=push_transcript,
                emergency_callback=push_emergency,
                assessment_callback=push_assessment,
                measurement_callback=push_measurement,
                options_callback=push_options,
                identity_callback=push_identity,
                resume_callback=push_resume,
                viseme_callback=push_visemes,
                resume_prompt=resume_prompt,
            )
        except ValueError as exc:
            await websocket.close(code=1008, reason=str(exc))
            return
        except Exception:
            logger.exception("Voice connect failed for %s", session_id)
            try:
                await websocket.send_json({"type": "error", "message": "connect_failed"})
            finally:
                await websocket.close(code=1011)
            return

        async def pump_outbound() -> None:
            """ADK live pipeline → WebSocket audio frames."""
            while live_voice_service.should_keep_pipeline_open(session_id):
                try:
                    async for chunk in live_voice_service.run_live_pipeline(session_id):
                        if chunk:
                            await websocket.send_bytes(chunk)
                except WebSocketDisconnect:
                    # Client closed mid-stream; cancellation will tear down
                    # the receive task as well.
                    return
                except Exception:
                    logger.exception(
                        "Outbound voice pump failed for %s", session_id
                    )
                    return

                if live_voice_service.should_keep_pipeline_open(session_id):
                    await asyncio.sleep(0.05)

        async def pump_inbound() -> None:
            """WebSocket frames → ADK live queue / control plane."""
            while True:
                try:
                    message = await websocket.receive()
                except WebSocketDisconnect:
                    return

                # FastAPI / Starlette gives us either bytes or text in
                # ``message``. Binary is microphone PCM; text is a JSON
                # control envelope. ``message["type"]`` is the wire
                # event (e.g. "websocket.disconnect") — not our payload
                # type — so disambiguate by key.
                if message.get("type") == "websocket.disconnect":
                    return

                if (data := message.get("bytes")) is not None:
                    try:
                        await live_voice_service.send_audio(session_id, data)
                    except ValueError:
                        # Session vanished — bail. The outer cleanup will
                        # close the socket.
                        return
                    except Exception:
                        logger.exception(
                            "send_audio failed for %s", session_id
                        )
                    continue

                text = message.get("text")
                if text is None:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    logger.warning(
                        "Voice WS %s: discarding non-JSON text frame", session_id
                    )
                    continue

                msg_type = payload.get("type") if isinstance(payload, dict) else None
                if msg_type == "mute":
                    live_voice_service.set_mute(session_id, True)
                    await websocket.send_json({"type": "status", "muted": True})
                elif msg_type == "unmute":
                    live_voice_service.set_mute(session_id, False)
                    await websocket.send_json({"type": "status", "muted": False})
                elif msg_type == "end_of_turn":
                    live_voice_service.end_user_turn(
                        session_id,
                        caption=str(payload.get("caption") or ""),
                    )
                    continue
                elif msg_type == "submit_measurement":
                    # The temperature-on-demand popup: the client already
                    # PUT the reading onto the session; drive a text turn so
                    # its turn_context carries the value and the engine
                    # continues without waiting for the patient to speak.
                    content = str(payload.get("content") or "").strip()
                    if content:
                        try:
                            live_voice_service.inject_text_turn(session_id, content)
                        except ValueError:
                            return
                    continue
                elif msg_type == "tap_reply":
                    # Quick-reply chip tap — same as submit_measurement: wins
                    # over whatever the mic is capturing. Tagged "button" so
                    # the nurse transcript shows how the answer was given.
                    content = str(payload.get("content") or "").strip()
                    if content:
                        try:
                            live_voice_service.inject_text_turn(
                                session_id, content, input_mode="button"
                            )
                        except ValueError:
                            return
                    continue
                elif msg_type == "end_call":
                    return
                else:
                    logger.debug(
                        "Voice WS %s: unknown control message %r",
                        session_id,
                        msg_type,
                    )

        outbound_task = asyncio.create_task(pump_outbound())
        inbound_task = asyncio.create_task(pump_inbound())
        try:
            done, pending = await asyncio.wait(
                {outbound_task, inbound_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            # Surface any unexpected task exceptions to the log without
            # raising — disconnect() must still run.
            for task in done:
                exc = task.exception()
                if exc is not None and not isinstance(exc, asyncio.CancelledError):
                    logger.exception(
                        "Voice WS %s task crashed", session_id, exc_info=exc
                    )
            # Wait briefly for cancellations so disconnect() sees no
            # in-flight ADK iteration when it closes the queue.
            await asyncio.gather(*pending, return_exceptions=True)
        finally:
            await live_voice_service.disconnect(session_id)
            try:
                await websocket.send_json({"type": "call_ended"})
            except Exception:
                # Socket already closed by the client — fine.
                pass
            try:
                await websocket.close()
            except Exception:
                pass
            logger.info("Voice call ended: %s", session_id)


# ── Doctor schedule endpoints ────────────────────────────────────────────────
