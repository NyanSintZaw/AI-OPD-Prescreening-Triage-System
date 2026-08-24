import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4
import asyncpg
from fastapi import (
    Depends,
    HTTPException,
    Request,
)
from app.database import get_connection, records_to_dicts

logger = logging.getLogger(__name__)
from app.schemas import (
    AssessmentReviewApproveRequest,
    AssessmentReviewCorrectRequest,
    AssessmentReviewOut,
    RoutingFeedbackOut,
    SbarPayload,
    SbarPreviewRequest,
)

from fastapi import APIRouter
from app.routers.deps import require_roles

router = APIRouter()

async def _serialize_review(
    connection: asyncpg.Connection, assessment_id: UUID
) -> dict:
    row = await connection.fetchrow(
        """
        SELECT
            ar.*,
            reviewer.full_name AS reviewer_name,
            pd.name_en AS proposed_department_name_en,
            pd.name_th AS proposed_department_name_th,
            cd.name_en AS confirmed_department_name_en,
            cd.name_th AS confirmed_department_name_th,
            (s.metadata->>'patient_contact_requested')::boolean AS patient_contact_requested,
            NULLIF(s.metadata->>'patient_contact_phone', '') AS patient_contact_phone,
            NULLIF(s.metadata->>'patient_contact_preferred_time', '') AS patient_contact_preferred_time,
            NULLIF(s.metadata->>'patient_contact_relation', '') AS patient_contact_relation,
            s.metadata->'triage_classification'->'disposition_reasons' AS disposition_reasons,
            s.metadata->'patient'->>'visit_id' AS visit_id,
            NULLIF(s.metadata->'patient'->>'patient_name', '') AS patient_name,
            NULLIF(s.metadata->'patient'->>'hn', '') AS patient_hn,
            s.metadata->'patient_history' AS patient_history,
            s.metadata->'vitals' AS vitals,
            s.metadata->'triage_classification'->>'symptoms_summary' AS ai_chief_complaint,
            s.metadata->'triage_classification'->>'key_reason' AS ai_illness_note,
            NULLIF(s.metadata->>'patient_follow_up', '') AS patient_follow_up,
            s.metadata->'his_routing'->>'status' AS his_routing_status,
            s.metadata->'his_routing'->>'queue_number' AS his_queue_number,
            s.metadata->'his_routing'->>'message_th' AS his_routing_message_th,
            s.metadata->'his_routing'->>'request_id' AS his_request_id,
            s.metadata->'rag_grounding' AS rag_grounding,
            ss.state->'measured_vitals' AS screening_measured_vitals,
            ss.state->'rejected_vitals' AS screening_rejected_vitals,
            ss.state->>'phase' AS screening_phase
        FROM assessment_reviews ar
        JOIN sessions s ON s.id = ar.session_id
        LEFT JOIN screening_sessions ss ON ss.session_id = ar.session_id
        LEFT JOIN admin_users reviewer ON reviewer.id = ar.reviewer_id
        LEFT JOIN departments pd ON pd.id = ar.proposed_department_id
        LEFT JOIN departments cd ON cd.id = ar.confirmed_department_id
        WHERE ar.assessment_id = $1
        """,
        assessment_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Assessment review not found")
    return _attach_missing_vitals(dict(row))


def _attach_missing_vitals(row: dict) -> dict:
    """Vitals context for nurse review, in two distinct flavours.

    ``missing_vitals``: core vitals (hr/rr/spo2/temp/sbp) never
    instrument-measured — the undertriage caution.

    ``rejected_vitals``: values that WERE reported but were physiologically
    impossible and so never reached the rules. The nurse must see the reported
    number flagged rather than a blank, because "patient said 50 °C" and "no
    thermometer reading" mean very different things at the bedside.

    Both are only meaningful once the engine disposed; interview/escalated
    rows carry null.
    """
    from app.services.screening.vitals import missing_core_vitals

    phase = row.pop("screening_phase", None)
    measured = row.pop("screening_measured_vitals", None)
    rejected = row.pop("screening_rejected_vitals", None)
    disposed = phase in ("disposed", "follow_up", "done")
    row["missing_vitals"] = missing_core_vitals(measured) if disposed else None
    row["rejected_vitals"] = (rejected or None) if disposed else None
    return row
@router.get("/admin/sessions/{session_id}/trace")
async def get_session_trace(
    session_id: UUID,
    _admin_user: dict = Depends(require_roles("nurse", "super_admin", "viewer")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Full AI decision trace for one session (SRS Explainability / F40).

    Returns the screening engine state (findings, slots, disposition with
    fired rules + manual citations) and the per-call ai_inference_audit
    timeline. Only available for sessions run by the screening engine v2.
    """

    state_row = await connection.fetchrow(
        """
        SELECT state, criteria_version_id, prompt_version, updated_at
        FROM screening_sessions WHERE session_id = $1
        """,
        session_id,
    )
    audit_rows = await connection.fetch(
        """
        SELECT turn_no, call_site, model_name, prompt_version, criteria_version_id,
               rules_trace, validator_result, ok, latency_ms, created_at
        FROM ai_inference_audit
        WHERE session_id = $1
        ORDER BY created_at ASC
        """,
        session_id,
    )
    if state_row is None and not audit_rows:
        raise HTTPException(
            status_code=404,
            detail="No screening-engine trace for this session",
        )

    engine_state = state_row["state"] if state_row else None
    if isinstance(engine_state, str):
        import json as _json

        engine_state = _json.loads(engine_state)
    return {
        "session_id": str(session_id),
        "criteria_version_id": (
            str(state_row["criteria_version_id"])
            if state_row and state_row["criteria_version_id"]
            else None
        ),
        "prompt_version": state_row["prompt_version"] if state_row else None,
        "updated_at": state_row["updated_at"] if state_row else None,
        "engine_state": engine_state,
        "audit": records_to_dicts(audit_rows),
    }


@router.get("/admin/reviews/pending-count")
async def count_pending_reviews(
    # Cheap badge feed for the in-app FAB and the desktop widget — the list
    # route below returns up to 200 fully-joined rows, far too fat to poll.
    _admin_user: dict = Depends(require_roles("nurse", "super_admin", "viewer")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    pending = await connection.fetchval(
        "SELECT COUNT(*) FROM assessment_reviews WHERE status = 'pending'"
    )
    return {"pending": pending or 0}


@router.get("/admin/reviews", response_model=list[AssessmentReviewOut])
async def list_assessment_reviews(
    status: str = "pending",
    # Read-only: viewers reach the review queue from the staff shortcut, but
    # approve/correct below stay nurse + super_admin.
    _admin_user: dict = Depends(require_roles("nurse", "super_admin", "viewer")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    rows = await connection.fetch(
        """
        SELECT
            ar.*,
            reviewer.full_name AS reviewer_name,
            pd.name_en AS proposed_department_name_en,
            pd.name_th AS proposed_department_name_th,
            cd.name_en AS confirmed_department_name_en,
            cd.name_th AS confirmed_department_name_th,
            (s.metadata->>'patient_contact_requested')::boolean AS patient_contact_requested,
            NULLIF(s.metadata->>'patient_contact_phone', '') AS patient_contact_phone,
            NULLIF(s.metadata->>'patient_contact_preferred_time', '') AS patient_contact_preferred_time,
            NULLIF(s.metadata->>'patient_contact_relation', '') AS patient_contact_relation,
            s.metadata->'triage_classification'->'disposition_reasons' AS disposition_reasons,
            s.metadata->'patient'->>'visit_id' AS visit_id,
            NULLIF(s.metadata->'patient'->>'patient_name', '') AS patient_name,
            NULLIF(s.metadata->'patient'->>'hn', '') AS patient_hn,
            s.metadata->'patient_history' AS patient_history,
            s.metadata->'vitals' AS vitals,
            s.metadata->'triage_classification'->>'symptoms_summary' AS ai_chief_complaint,
            s.metadata->'triage_classification'->>'key_reason' AS ai_illness_note,
            NULLIF(s.metadata->>'patient_follow_up', '') AS patient_follow_up,
            s.metadata->'his_routing'->>'status' AS his_routing_status,
            s.metadata->'his_routing'->>'queue_number' AS his_queue_number,
            s.metadata->'his_routing'->>'message_th' AS his_routing_message_th,
            s.metadata->'his_routing'->>'request_id' AS his_request_id,
            s.metadata->'rag_grounding' AS rag_grounding,
            ss.state->'measured_vitals' AS screening_measured_vitals,
            ss.state->'rejected_vitals' AS screening_rejected_vitals,
            ss.state->>'phase' AS screening_phase
        FROM assessment_reviews ar
        JOIN sessions s ON s.id = ar.session_id
        LEFT JOIN screening_sessions ss ON ss.session_id = ar.session_id
        LEFT JOIN admin_users reviewer ON reviewer.id = ar.reviewer_id
        LEFT JOIN departments pd ON pd.id = ar.proposed_department_id
        LEFT JOIN departments cd ON cd.id = ar.confirmed_department_id
        WHERE (
            $1 = 'all'
            OR ($1 = 'reviewed' AND ar.status::text IN ('approved', 'corrected'))
            OR ar.status::text = $1
        )
        ORDER BY ar.created_at DESC
        LIMIT 200
        """,
        status,
    )
    return [_attach_missing_vitals(row) for row in records_to_dicts(rows)]


def _resolve_request_id(prior: dict[str, Any] | None, department_code: str) -> str:
    """Idempotency key for one patient assignment.

    Reuse the stored key when the destination is unchanged, so a retry after a
    timeout cannot create a second queue row. Allocate a fresh one when the
    nurse genuinely reroutes, because that IS a different assignment and must
    not be deduplicated away by the hospital.

    Pure, so the rule is testable without a database. Shaped like the
    hospital's own sample (prefix + date + sequence) for their support team.
    """
    prior = prior or {}
    if prior.get("request_id") and prior.get("department_code") == department_code:
        return str(prior["request_id"])
    return f"MFU-{datetime.now(timezone.utc):%Y%m%d}-{uuid4().hex[:6].upper()}"


async def _set_visit_passthrough(
    connection: asyncpg.Connection, session_id, visit_id: str | None
) -> None:
    """Nurse-entered VN for a session whose HIS lookup had no current visit.

    Fills metadata.patient.visit_id only — never touches identity (hn), and
    is a no-op for anonymous sessions (no patient link to hang a VN on)."""
    cleaned = (visit_id or "").strip()
    if not cleaned:
        return
    row = await connection.fetchrow(
        "SELECT metadata FROM sessions WHERE id = $1", session_id
    )
    if row is None:
        return
    metadata = dict(row["metadata"] or {})
    patient = dict(metadata.get("patient") or {})
    if not patient.get("hn"):
        return
    patient["visit_id"] = cleaned
    metadata["patient"] = patient
    await connection.execute(
        "UPDATE sessions SET metadata = $2::jsonb WHERE id = $1",
        session_id,
        metadata,
    )


async def _push_his_routing(
    request: Request,
    connection: asyncpg.Connection,
    *,
    session_id,
    department_id,
    confirmed_by: str,
    rerouted: bool,
    chief_complaint: str | None = None,
    illness_note: str | None = None,
    sbar: SbarPayload | None = None,
) -> None:
    """Stage-2 HIS write-back: send the patient to their destination
    department now that a nurse has signed off (the hospital's
    patient-assignment API, Data Requirements V1 §2.2/§4.4).

    Best-effort — never raises into the endpoint. The whole outcome is stored
    on ``session.metadata.his_routing`` so the nurse sees the queue number, or
    an actionable reason. Cases we cannot even attempt are recorded as
    ``skipped`` with a reason rather than silently doing nothing, so "not
    applicable" is distinguishable from "never ran".
    """
    from app.services.screening.his import (
        AssignmentResult,
        his_department_id,
        his_department_name,
    )
    from app.services.screening.his.sbar import build_mfu_prescreen, build_sbar

    session_row = await connection.fetchrow(
        "SELECT metadata FROM sessions WHERE id = $1", session_id
    )
    if session_row is None:
        # Nowhere to record anything; the endpoint's own 404 covers the caller.
        logger.warning("[session=%s] HIS stage-2: session vanished", session_id)
        return
    metadata = dict(session_row["metadata"] or {})
    prior = metadata.get("his_routing") or {}

    async def _record(block: dict[str, Any]) -> None:
        metadata["his_routing"] = {
            **block,
            "rerouted": rerouted,
            "confirmed_by": confirmed_by,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        await connection.execute(
            "UPDATE sessions SET metadata = $2::jsonb WHERE id = $1",
            session_id,
            metadata,
        )

    if not department_id:
        await _record({"status": "skipped", "reason": "no_department"})
        return
    patient = metadata.get("patient") or {}
    hn = patient.get("hn")
    if not hn:
        await _record({"status": "skipped", "reason": "no_patient_link"})
        return
    # VN passthrough when the HIS knew an open visit at link time; the HIS
    # resolves the HN's active visit itself otherwise.
    visit_id = patient.get("visit_id")
    dept = await connection.fetchrow(
        "SELECT code, name_th FROM departments WHERE id = $1", department_id
    )
    if dept is None:
        await _record({"status": "skipped", "reason": "unknown_department"})
        return

    his_dept = his_department_name(dept["code"]) or dept["name_th"] or dept["code"]
    base_department_id = his_department_id(dept["code"])
    if not base_department_id:
        # Never invent a department id: the hospital would queue the patient
        # somewhere real, or reject the call.
        await _record(
            {
                "status": "skipped",
                "reason": "no_department_id",
                "department": his_dept,
                "department_code": dept["code"],
            }
        )
        return

    engine_sbar = build_sbar(
        metadata,
        department_th=his_dept,
        rerouted=rerouted,
        chief_complaint=chief_complaint,
        illness_note=illness_note,
    )
    sent_sbar = sbar.model_dump() if sbar is not None else engine_sbar
    edited = sent_sbar != engine_sbar

    request_id = _resolve_request_id(prior, dept["code"])
    mfu_prescreen = build_mfu_prescreen(
        metadata,
        confirmed_by=confirmed_by,
        rerouted=rerouted,
        session_id=str(session_id),
    )
    adapter = request.app.state.his_adapter
    try:
        result = await adapter.confirm_routing(
            visit_id,
            request_id=request_id,
            hn=hn,
            base_department_id=base_department_id,
            sbar=sent_sbar,
            mfu_prescreen=mfu_prescreen,
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("[session=%s] HIS stage-2 assignment raised", session_id)
        # "unknown", never "failed": the queue row may exist, and the stored
        # request_id makes a retry safe.
        result = AssignmentResult(status="unknown", request_id=request_id)

    block: dict[str, Any] = {
        "status": result.status,
        "request_id": result.request_id,
        "department": his_dept,
        "department_code": dept["code"],
        "base_department_id": base_department_id,
        "queue_number": result.queue_number,
        "visit_queue_id": result.visit_queue_id,
        "queue_status": result.queue_status,
        "sbar_id": result.sbar_id,
        "message": result.message,
        "message_th": result.message_th,
        # Audit: what actually went to the hospital, and the engine's original
        # when the nurse changed it. Presence of sbar_engine == it was edited.
        "sbar": sent_sbar,
        "sbar_edited": edited,
    }
    if edited:
        block["sbar_engine"] = engine_sbar
    await _record(block)


# ── Hospital DB (mock HIS) read-only proxy for the admin dashboard ──────────
# Lets the demo show the visit record go blank → screened → routed inside our
# app, framed as "the admin also oversees the hospital DB". Only meaningful in
# HIS_MODE=http; degrades to an empty/unavailable response otherwise.
@router.post(
    "/admin/reviews/{assessment_id}/sbar-preview", response_model=SbarPayload
)
async def preview_review_sbar(
    assessment_id: UUID,
    payload: SbarPreviewRequest,
    connection: asyncpg.Connection = Depends(get_connection),
    _admin_user: dict = Depends(require_roles("nurse", "super_admin")),
):
    """Build the SBAR handover the nurse is about to send, so it can be shown
    and edited before it fires.

    A POST because the draft it depends on (complaint, note, chosen
    department) is free text the nurse has not saved yet. Called once when the
    confirm dialog opens — deliberately NOT a field on the review list, which
    would build an SBAR for every row on every poll.
    """
    row = await connection.fetchrow(
        """
        SELECT ar.session_id, ar.proposed_department_id, ar.confirmed_department_id,
               s.metadata
        FROM assessment_reviews ar
        JOIN sessions s ON s.id = ar.session_id
        WHERE ar.assessment_id = $1
        """,
        assessment_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Assessment review not found")

    from app.services.screening.his import his_department_name
    from app.services.screening.his.sbar import build_sbar

    department_id = (
        payload.department_id
        or row["confirmed_department_id"]
        or row["proposed_department_id"]
    )
    dept = (
        await connection.fetchrow(
            "SELECT code, name_th FROM departments WHERE id = $1", department_id
        )
        if department_id
        else None
    )
    his_dept = ""
    if dept is not None:
        his_dept = his_department_name(dept["code"]) or dept["name_th"] or dept["code"]

    metadata = dict(row["metadata"] or {})
    return SbarPayload(
        **build_sbar(
            metadata,
            department_th=his_dept,
            # The nurse is previewing whatever they currently have selected;
            # whether that counts as a reroute is only settled on submit.
            rerouted=bool(
                payload.department_id
                and payload.department_id != row["proposed_department_id"]
            ),
            chief_complaint=payload.chief_complaint,
            illness_note=payload.illness_note,
        )
    )


@router.post("/admin/reviews/{assessment_id}/approve", response_model=AssessmentReviewOut)
async def approve_assessment_review(
    assessment_id: UUID,
    payload: AssessmentReviewApproveRequest,
    request: Request,
    admin_user: dict = Depends(require_roles("nurse", "super_admin")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    row = await connection.fetchrow(
        """
        UPDATE assessment_reviews
        SET status = 'approved',
            reviewer_id = $2,
            confirmed_department_id = COALESCE(confirmed_department_id, proposed_department_id),
            notes = $3,
            ai_assessment_score = $4,
            chief_complaint = $5,
            illness_note = $6,
            ai_assessment_scale = 10,
            reviewed_at = NOW(),
            updated_at = NOW()
        WHERE assessment_id = $1
        RETURNING session_id, confirmed_department_id
        """,
        assessment_id,
        admin_user["id"],
        payload.notes,
        payload.ai_assessment_score,
        payload.chief_complaint,
        payload.illness_note,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Assessment review not found")

    if row["confirmed_department_id"]:
        await connection.execute(
            """
            INSERT INTO department_recommendations (
                session_id, assessment_id, department_id, confidence, reason
            )
            VALUES ($1, $2, $3, $4, $5)
            """,
            row["session_id"],
            assessment_id,
            row["confirmed_department_id"],
            1.0,
            "Approved by OPD nurse review",
        )

    await _set_visit_passthrough(connection, row["session_id"], payload.visit_id)
    await _push_his_routing(
        request,
        connection,
        session_id=row["session_id"],
        department_id=row["confirmed_department_id"],
        confirmed_by=str(admin_user.get("email") or admin_user["id"]),
        rerouted=False,
        chief_complaint=payload.chief_complaint,
        illness_note=payload.illness_note,
        sbar=payload.sbar,
    )

    return await _serialize_review(connection, assessment_id)


@router.post("/admin/reviews/{assessment_id}/correct", response_model=AssessmentReviewOut)
async def correct_assessment_review(
    assessment_id: UUID,
    payload: AssessmentReviewCorrectRequest,
    request: Request,
    admin_user: dict = Depends(require_roles("nurse", "super_admin")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    review_before = await connection.fetchrow(
        """
        SELECT session_id, proposed_department_id
        FROM assessment_reviews
        WHERE assessment_id = $1
        """,
        assessment_id,
    )
    if review_before is None:
        raise HTTPException(status_code=404, detail="Assessment review not found")

    await connection.execute(
        """
        UPDATE assessment_reviews
        SET status = 'corrected',
            reviewer_id = $2,
            confirmed_department_id = $3,
            notes = $4,
            ai_assessment_score = $5,
            chief_complaint = $6,
            illness_note = $7,
            ai_assessment_scale = 10,
            reviewed_at = NOW(),
            updated_at = NOW()
        WHERE assessment_id = $1
        """,
        assessment_id,
        admin_user["id"],
        payload.confirmed_department_id,
        payload.reason,
        payload.ai_assessment_score,
        payload.chief_complaint,
        payload.illness_note,
    )

    await connection.execute(
        """
        INSERT INTO department_recommendations (
            session_id, assessment_id, department_id, confidence, reason
        )
        VALUES ($1, $2, $3, $4, $5)
        """,
        review_before["session_id"],
        assessment_id,
        payload.confirmed_department_id,
        1.0,
        "Corrected by OPD nurse review",
    )

    await connection.execute(
        """
        INSERT INTO routing_feedback (
            session_id,
            assessment_id,
            assessment_result_id,
            original_department_id,
            corrected_department_id,
            reported_by,
            nurse_user_id,
            reason,
            feedback_text
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """,
        review_before["session_id"],
        assessment_id,
        None,
        review_before["proposed_department_id"],
        payload.confirmed_department_id,
        admin_user["id"],
        None,
        payload.reason,
        payload.reason,
    )

    await _set_visit_passthrough(
        connection, review_before["session_id"], payload.visit_id
    )
    await _push_his_routing(
        request,
        connection,
        session_id=review_before["session_id"],
        department_id=payload.confirmed_department_id,
        confirmed_by=str(admin_user.get("email") or admin_user["id"]),
        rerouted=True,
        chief_complaint=payload.chief_complaint,
        illness_note=payload.illness_note,
        sbar=payload.sbar,
    )

    return await _serialize_review(connection, assessment_id)


@router.get("/admin/feedback", response_model=list[RoutingFeedbackOut])
async def list_routing_feedback(
    # Read-only, same as /admin/reviews above.
    _admin_user: dict = Depends(require_roles("nurse", "super_admin", "viewer")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    rows = await connection.fetch(
        """
        SELECT
            rf.*,
            corrected.name_en AS corrected_department_name_en,
            corrected.name_th AS corrected_department_name_th,
            reporter.full_name AS reporter_name
        FROM routing_feedback rf
        LEFT JOIN departments corrected ON corrected.id = rf.corrected_department_id
        LEFT JOIN admin_users reporter ON reporter.id = rf.reported_by
        ORDER BY rf.created_at DESC
        LIMIT 200
        """
    )
    return records_to_dicts(rows)


# ---------------------------------------------------------------------------
# Voice WebSocket — turn-based voice bridge (Google STT → screening engine →
# Google Cloud TTS; no Gemini Live)
# ---------------------------------------------------------------------------
#
# Protocol (see app/services/screening/voice_bridge.py for state details):
#
#   Client → server
#     bytes                          raw PCM 16-bit 16 kHz mono audio chunk
#     {"type": "mute"}               suppress mic forward to the live pipeline
#     {"type": "unmute"}             resume forwarding
#     {"type": "end_of_turn"}        force end of caller turn (activity_end)
#     {"type": "end_call"}           caller hung up — close gracefully
#
#   Server → client
#     bytes                          raw PCM agent audio (24 kHz mono)
#     {"type": "status", "muted":…}  ack for mute / unmute
#     {"type": "call_ended"}         sent right before the socket closes
#     {"type": "error",   "message"} fatal error before close
#
# The endpoint runs two tasks concurrently: one drives ADK's bidirectional
# stream and forwards audio to the browser, the other listens for inbound
# audio + control messages. When either task finishes (clean disconnect,
# explicit end_call, or a crash) we cancel the sibling task and run
# disconnect() — which flushes the accumulated transcript through the
# normal text triage pipeline so DB rows and the mock notifier still fire.

