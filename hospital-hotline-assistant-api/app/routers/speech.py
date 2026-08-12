import logging
from fastapi import (
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import Response
from app.services.speech_adapter import SttClient, TtsClient

logger = logging.getLogger(__name__)
from app.schemas import (
    SttResponse,
    TtsRequest,
)

from fastapi import APIRouter

router = APIRouter()

@router.post("/tts")
async def text_to_speech(payload: TtsRequest, request: Request):
    """Synthesize speech for the given text. Returns audio/mpeg (MP3) bytes."""

    tts_client: TtsClient = request.app.state.tts_client
    try:
        audio_bytes = await tts_client.synthesize(
            text=payload.text,
            language=payload.language,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={"Content-Disposition": 'inline; filename="speech.mp3"'},
    )


@router.post("/stt", response_model=SttResponse)
async def speech_to_text(
    request: Request,
    audio: UploadFile = File(..., description="Short audio clip from MediaRecorder"),
    language: str = Form("en"),
):
    """Transcribe a short audio clip. Returns the recognized text."""

    if language not in {"en", "th"}:
        raise HTTPException(status_code=400, detail="language must be 'en' or 'th'")

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="audio file is empty")

    stt_client: SttClient = request.app.state.stt_client
    try:
        result = await stt_client.transcribe(
            audio_bytes=audio_bytes,
            language=language,
            mime_type=audio.content_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return SttResponse(
        transcript=result.transcript,
        confidence=result.confidence,
        language_code=result.language_code,
    )

