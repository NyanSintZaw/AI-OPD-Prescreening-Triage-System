import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID
import asyncpg
from fastapi import (
    Depends,
    HTTPException,
    Request,
    status,
)
from app.database import get_connection, record_to_dict
from app.services.surveillance_extractor import extract_and_save as surveillance_extract
from app.services.slip_code import slip_code_for

logger = logging.getLogger(__name__)
from app.schemas import (
    LinkVisitRequest,
    LinkVisitResponse,
    ConfirmVisitNameRequest,
    ConfirmVisitNameResponse,
    PatientHistoryIntakeRequest,
    PatientHistoryIntakeResponse,
    SessionByVisitOut,
    SessionCreate,
    SessionLocationUpdate,
    SessionOut,
    SessionUpdate,
)

from fastapi import APIRouter

router = APIRouter()

@router.post("/sessions", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(payload: SessionCreate, connection: asyncpg.Connection = Depends(get_connection)):
    record = await connection.fetchrow(
        """
        INSERT INTO sessions (language, user_agent, ip_hash, metadata)
        VALUES ($1, $2, $3, $4::jsonb)
        RETURNING *
        """,
        payload.language,
        payload.user_agent,
        payload.ip_hash,
        payload.metadata,
    )
    # Stamp the slip code (shown on the patient slip, searched by nurses at
    # the destination) so every session — anonymous or visit-linked — has one.
    metadata = dict(record["metadata"] or {})
    metadata["slip_code"] = slip_code_for(str(record["id"]))
    record = await connection.fetchrow(
        "UPDATE sessions SET metadata = $2::jsonb WHERE id = $1 RETURNING *",
        record["id"],
        metadata,
    )
    return record_to_dict(record)


@router.post("/sessions/{session_id}/link-visit", response_model=LinkVisitResponse)
async def link_visit(
    session_id: UUID,
    payload: LinkVisitRequest,
    request: Request,
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Link a hospital visit to this session.

    The patient types (or scans) the visit ID issued at the registration
    booth; we validate it against the HIS and pull demographics (birthdate →
    age) and any HIS-recorded vitals into session metadata so the screening
    engine can pre-fill them. Unknown visit → ``linked=false`` and the
    patient continues anonymously.
    """
    from app.services.screening import templates as screening_templates

    session_row = await connection.fetchrow(
        "SELECT metadata, language FROM sessions WHERE id = $1", session_id
    )
    if session_row is None:
        raise HTTPException(status_code=404, detail="Session not found")

    adapter = request.app.state.his_adapter
    info = await adapter.validate_visit(payload.visit_id)
    if info is None or not info.is_active:
        return LinkVisitResponse(linked=False, visit_id=payload.visit_id)

    metadata = dict(session_row["metadata"] or {})
    # Re-linking (e.g. after a rejected name confirm): never carry the
    # previous patient's HIS prefill into the new link.
    from app.services.visit_confirm import strip_his_prefill

    strip_his_prefill(metadata)
    metadata["visit"] = {
        "visit_id": info.visit_id,
        "hn": info.patient_id,
        "patient_name": info.patient_name,
        "birthdate": info.birthdate,
        "age_years": info.age_years,
        "appointment": info.appointment,
        "linked_at": datetime.now(timezone.utc).isoformat(),
        # Identity is asked once per kiosk walk-up: a relink within the same
        # run (start over) carries the already-spoken confirmation.
        "name_confirmed": bool(payload.preconfirmed and info.patient_name),
    }
    if info.patient_history is not None:
        metadata["patient_history"] = {
            "is_first_time": info.patient_history.is_first_time,
            "smoking_alcohol": info.patient_history.smoking_alcohol,
            "allergies": info.patient_history.allergies,
            "chronic_conditions": info.patient_history.chronic_conditions,
            "past_surgeries": info.patient_history.past_surgeries,
            "family_history": info.patient_history.family_history,
            "last_weight_kg": info.patient_history.last_weight_kg,
            "last_height_cm": info.patient_history.last_height_cm,
            "vitals_measured_at": info.patient_history.vitals_measured_at,
        }
    # Seed session vitals with anything the HIS already holds; a later cuff
    # reading or manual entry overrides these.
    his_vitals = {k: v for k, v in (info.vitals or {}).items() if v is not None}
    if his_vitals:
        merged = dict(metadata.get("vitals") or {})
        merged.update(his_vitals)
        merged.setdefault("source", "his")
        metadata["vitals"] = merged
    # Skip asking weight/height when HN has a recent measurement on file.
    from app.services.screening.weight_height import merge_recent_weight_height_into_vitals

    metadata["vitals"] = merge_recent_weight_height_into_vitals(
        dict(metadata.get("vitals") or {}),
        info.patient_history,
    )
    await connection.execute(
        "UPDATE sessions SET metadata = $2::jsonb WHERE id = $1",
        session_id,
        metadata,
    )
    # Open the conversation with a persisted greeting (personalized when the
    # HIS gave us a name) so chat shows it on load and the nurse transcript
    # keeps it; voice speaks the same line from the bridge.
    has_messages = await connection.fetchval(
        "SELECT EXISTS (SELECT 1 FROM messages WHERE session_id = $1)", session_id
    )
    if not has_messages:
        language = session_row["language"] or "th"
        await connection.execute(
            """
            INSERT INTO messages (session_id, role, input_mode, content)
            VALUES ($1, 'assistant', 'text', $2)
            """,
            session_id,
            screening_templates.greeting_line(info.patient_name, language),
        )
    return LinkVisitResponse(
        linked=True,
        visit_id=info.visit_id,
        patient_name=info.patient_name,
        age_years=info.age_years,
        appointment=info.appointment,
        has_his_vitals=bool(his_vitals),
        is_first_time=bool(
            info.patient_history.is_first_time if info.patient_history else True
        ),
        hn=info.patient_id,
    )


@router.get("/sessions/by-visit/{visit_id}", response_model=SessionByVisitOut)
async def get_session_by_visit(
    visit_id: str,
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Return the most recent active session linked to this hospital visit (VN).

    Used by the kiosk before creating a new session: if the patient hung up
    or walked away mid-interview and re-enters the same VN, resume the prior
    session (screening engine state is already in Postgres).
    """
    from app.services.session_resume import find_active_session_by_visit_id
    from app.services.visit_confirm import needs_history_intake

    cleaned = visit_id.strip()
    if not cleaned:
        return SessionByVisitOut(found=False, visit_id=visit_id)

    record = await find_active_session_by_visit_id(connection, cleaned)
    if record is None:
        return SessionByVisitOut(found=False, visit_id=cleaned)

    session = record_to_dict(record)
    visit_meta = (session.get("metadata") or {}).get("visit") or {}
    patient_name = visit_meta.get("patient_name")
    needs_history = needs_history_intake(session.get("metadata"))
    return SessionByVisitOut(
        found=True,
        visit_id=cleaned,
        session=session,
        status=str(session.get("status") or "") or None,
        patient_name=patient_name if isinstance(patient_name, str) else None,
        name_confirmed=bool(visit_meta.get("name_confirmed")),
        needs_history_intake=needs_history,
    )


@router.post(
    "/sessions/{session_id}/patient-history",
    response_model=PatientHistoryIntakeResponse,
)
async def save_patient_history(
    session_id: UUID,
    payload: PatientHistoryIntakeRequest,
    request: Request,
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Persist first-time-patient history to session metadata and the HIS HN.

    Gated for booth intake after name confirmation. Writes through
    ``HisAdapter.push_patient_history`` so returning visits see the data.
    """
    from app.services.patient_history import store_patient_history

    try:
        result = await store_patient_history(
            connection,
            session_id,
            {
                "smoking_alcohol": payload.smoking_alcohol,
                "allergies": payload.allergies,
                "chronic_conditions": payload.chronic_conditions,
                "past_surgeries": payload.past_surgeries,
                "family_history": payload.family_history,
            },
            his_adapter=request.app.state.his_adapter,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Session not found")

    return PatientHistoryIntakeResponse(
        saved=result["saved"],
        pushed_to_his=result["pushed_to_his"],
        is_first_time=False,
        hn=result["hn"],
    )


@router.delete("/sessions/{session_id}/link-visit", response_model=SessionOut)
async def unlink_visit(
    session_id: UUID,
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Clear the linked hospital visit so the patient can re-enter a VN.

    Used when name confirmation fails (\"Is this you?\" → No). Does not delete
    the session or screening state — drops ``metadata.visit`` plus any
    HIS-derived prefill (history, HIS-sourced vitals) of the wrong patient.
    """
    from app.services.visit_confirm import strip_his_prefill

    session_row = await connection.fetchrow(
        "SELECT metadata FROM sessions WHERE id = $1", session_id
    )
    if session_row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    metadata = dict(session_row["metadata"] or {})
    metadata.pop("visit", None)
    strip_his_prefill(metadata)
    record = await connection.fetchrow(
        "UPDATE sessions SET metadata = $2::jsonb WHERE id = $1 RETURNING *",
        session_id,
        metadata,
    )
    return record_to_dict(record)


def _screening_model():
    """The engine's shared chat model (or None) for the gate backstop."""
    from app.main import app

    try:
        return app.state.triage_service.triage_engine._model
    except AttributeError:
        return None


@router.post(
    "/sessions/{session_id}/confirm-visit-name",
    response_model=ConfirmVisitNameResponse,
)
async def confirm_visit_name(
    session_id: UUID,
    payload: ConfirmVisitNameRequest,
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Confirm or reject the HIS patient name after link-visit.

    Buttons send ``confirmed=true/false``; typed/spoken replies send ``text``
    and are classified by the shared yes/no NLU. A ``no`` decision unlinks the
    visit so the kiosk can re-prompt for VN. An unclear reply returns 422 and
    is re-asked at most MAX_IDENTITY_RETRIES times, then treated as rejected —
    fail closed like the voice identity gate (never interview an unverified
    identity).
    """
    from app.services.screening.nlu_yesno import classify_yes_no
    from app.services.visit_confirm import (
        MAX_IDENTITY_RETRIES,
        NoVisitLinkedError,
        apply_confirm_decision,
    )

    if payload.confirmed is True:
        decision: str = "yes"
    elif payload.confirmed is False:
        decision = "no"
    elif payload.text and payload.text.strip():
        decision = classify_yes_no(payload.text)
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide confirmed=true/false or a non-empty text reply",
        )

    session_row = await connection.fetchrow(
        "SELECT metadata, language FROM sessions WHERE id = $1", session_id
    )
    if session_row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    metadata = dict(session_row["metadata"] or {})

    if decision in ("uncertain", "other") and payload.text:
        # LLM backstop before the fail-closed 422/retry path: rescue
        # free-phrased confirms/denials the regex vocabulary misses. Any
        # backstop failure → "unclear" → the retry flow below, unchanged.
        from app.services.screening.nlu_backstop import confirm_gate

        verdict = await confirm_gate(
            _screening_model(),
            "identity_yesno",
            payload.text,
            str(session_row.get("language") or "th"),
            context=str((metadata.get("visit") or {}).get("patient_name") or ""),
        )
        if verdict in ("yes", "no"):
            # Definitive answer — applied below; the counter reset happens in
            # the shared definitive-decision block.
            decision = str(verdict)

    if decision in ("uncertain", "other"):
        attempts = int(metadata.get("confirm_name_attempts") or 0) + 1
        if attempts < MAX_IDENTITY_RETRIES:
            metadata["confirm_name_attempts"] = attempts
            await connection.execute(
                "UPDATE sessions SET metadata = $2::jsonb WHERE id = $1",
                session_id,
                metadata,
            )
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "unclear",
                    "retries_left": MAX_IDENTITY_RETRIES - attempts,
                },
            )
        decision = "no"  # retry cap exhausted — reject, exactly like voice

    if "confirm_name_attempts" in metadata:
        # Definitive decision (or cap hit): reset the counter so a later
        # re-link starts a fresh confirm.
        metadata.pop("confirm_name_attempts")
        await connection.execute(
            "UPDATE sessions SET metadata = $2::jsonb WHERE id = $1",
            session_id,
            metadata,
        )

    try:
        outcome = await apply_confirm_decision(connection, session_id, decision)
    except ValueError:
        raise HTTPException(status_code=404, detail="Session not found")
    except NoVisitLinkedError:
        raise HTTPException(status_code=400, detail="No visit linked to this session")

    return ConfirmVisitNameResponse(
        decision=outcome.decision,  # type: ignore[arg-type]
        name_confirmed=outcome.name_confirmed,
        unlinked=outcome.unlinked,
        patient_name=outcome.patient_name,
    )


@router.get("/sessions/{session_id}", response_model=SessionOut)
async def get_session(session_id: UUID, connection: asyncpg.Connection = Depends(get_connection)):
    record = await connection.fetchrow("SELECT * FROM sessions WHERE id = $1", session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return record_to_dict(record)

@router.patch("/sessions/{session_id}", response_model=SessionOut)
async def update_session(
    session_id: UUID,
    payload: SessionUpdate,
    request: Request,
    connection: asyncpg.Connection = Depends(get_connection),
):
    ended_sql = "NOW()" if payload.status in {"completed", "reset", "escalated"} else "ended_at"
    record = await connection.fetchrow(
        f"""
        UPDATE sessions
        SET status = $2, ended_at = {ended_sql}
        WHERE id = $1
        RETURNING *
        """,
        session_id,
        payload.status,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Fire AI disease-keyword extraction as a background task when a session
    # completes. Uses a fresh connection from the pool so the response is
    # returned immediately without waiting for the Gemini call to finish.
    if payload.status == "completed":
        pool = request.app.state.db_pool
        asyncio.create_task(
            _run_surveillance_extract(pool=pool, session_id=str(session_id))
        )

    return record_to_dict(record)


async def _run_surveillance_extract(
    *, pool: asyncpg.Pool, session_id: str
) -> None:
    """Acquire a fresh connection and run the surveillance extractor."""
    async with pool.acquire() as conn:
        await surveillance_extract(connection=conn, session_id=session_id)

@router.put("/sessions/{session_id}/location")
async def update_session_location(
    session_id: UUID,
    payload: SessionLocationUpdate,
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Save the patient-reported area for a session.
    Called by the chat UI after the user answers the location prompt.
    """
    record = await connection.fetchrow(
        """
        UPDATE sessions SET location_area = $2
        WHERE id = $1
        RETURNING id, location_area
        """,
        session_id,
        payload.location_area.strip(),
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": str(record["id"]), "location_area": record["location_area"]}

