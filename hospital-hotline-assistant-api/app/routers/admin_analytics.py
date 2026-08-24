import asyncio
import logging
from datetime import datetime, timezone
import asyncpg
from fastapi import (
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse
from app.config import settings
from app.database import get_connection, records_to_dicts

logger = logging.getLogger(__name__)
from app.schemas import (
    ConversationSummaryOut,
    SurveillanceSummaryOut,
    TriageStatsOut,
)

from fastapi import APIRouter
from app.routers.deps import require_roles

router = APIRouter()

@router.get("/conversation-summary", response_model=list[ConversationSummaryOut])
async def conversation_summary(
    _admin_user: dict = Depends(require_roles("super_admin", "viewer", "nurse")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    records = await connection.fetch(
        """
        SELECT
            cs.*,
            COALESCE((s.metadata->>'alert_sent')::boolean, FALSE) AS has_alert,
            s.metadata->>'escalation_reason' AS escalation_reason
        FROM conversation_summary cs
        JOIN sessions s ON s.id = cs.session_id
        ORDER BY cs.started_at DESC
        LIMIT 100
        """
    )
    return records_to_dicts(records)

@router.get("/admin/surveillance", response_model=SurveillanceSummaryOut)
async def get_surveillance_summary(
    days: int = Query(7, ge=1, le=90),
    _admin_user: dict = Depends(require_roles("super_admin", "nurse", "viewer")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Aggregate disease-surveillance data for the admin outbreak dashboard."""

    # Total classification events in the window
    total = await connection.fetchval(
        "SELECT COUNT(*) FROM disease_surveillance WHERE reported_at >= NOW() - INTERVAL '1 day' * $1",
        days,
    ) or 0

    # Top symptom keywords (unnested from the array)
    top_rows = await connection.fetch(
        """
        SELECT keyword, COUNT(*) AS count
        FROM disease_surveillance, UNNEST(symptom_keywords) AS keyword
        WHERE reported_at >= NOW() - INTERVAL '1 day' * $1
          AND keyword <> ''
        GROUP BY keyword
        ORDER BY count DESC
        LIMIT 20
        """,
        days,
    )

    # Symptoms by area
    area_rows = await connection.fetch(
        """
        SELECT COALESCE(location_area, 'Unknown') AS area, keyword, COUNT(*) AS count
        FROM disease_surveillance, UNNEST(symptom_keywords) AS keyword
        WHERE reported_at >= NOW() - INTERVAL '1 day' * $1
          AND keyword <> ''
        GROUP BY area, keyword
        ORDER BY area, count DESC
        """,
        days,
    )

    # Daily case counts
    trend_rows = await connection.fetch(
        """
        SELECT DATE(reported_at AT TIME ZONE 'UTC') AS date, COUNT(*) AS count
        FROM disease_surveillance
        WHERE reported_at >= NOW() - INTERVAL '1 day' * $1
        GROUP BY date
        ORDER BY date ASC
        """,
        days,
    )

    # Severity distribution
    severity_rows = await connection.fetch(
        """
        SELECT severity_level, COUNT(*) AS count
        FROM disease_surveillance
        WHERE reported_at >= NOW() - INTERVAL '1 day' * $1
        GROUP BY severity_level
        ORDER BY count DESC
        """,
        days,
    )

    # Outbreak alerts: keywords with 2× or more increase vs previous period
    alert_rows = await connection.fetch(
        """
        WITH recent AS (
            SELECT keyword, COALESCE(location_area, 'Unknown') AS area, COUNT(*) AS cnt
            FROM disease_surveillance, UNNEST(symptom_keywords) AS keyword
            WHERE reported_at >= NOW() - INTERVAL '1 day' * $1 AND keyword <> ''
            GROUP BY keyword, area
        ),
        previous AS (
            SELECT keyword, COALESCE(location_area, 'Unknown') AS area, COUNT(*) AS cnt
            FROM disease_surveillance, UNNEST(symptom_keywords) AS keyword
            WHERE reported_at >= NOW() - INTERVAL '1 day' * $2
              AND reported_at < NOW() - INTERVAL '1 day' * $1 AND keyword <> ''
            GROUP BY keyword, area
        )
        SELECT r.keyword, r.area,
               r.cnt  AS recent_count,
               COALESCE(p.cnt, 0) AS previous_count,
               ROUND(
                   CASE WHEN COALESCE(p.cnt, 0) = 0 THEN 100.0
                        ELSE (r.cnt - p.cnt)::NUMERIC / p.cnt * 100
                   END, 1
               ) AS increase_pct
        FROM recent r
        LEFT JOIN previous p USING (keyword, area)
        WHERE r.cnt >= 3
          AND (COALESCE(p.cnt, 0) = 0 OR r.cnt >= p.cnt * 2)
        ORDER BY increase_pct DESC
        LIMIT 10
        """,
        days,
        days * 2,
    )

    return SurveillanceSummaryOut(
        days=days,
        total_reports=total,
        top_symptoms=[{"keyword": r["keyword"], "count": r["count"]} for r in top_rows],
        by_area=[{"area": r["area"], "keyword": r["keyword"], "count": r["count"]} for r in area_rows],
        daily_trend=[{"date": str(r["date"]), "count": r["count"]} for r in trend_rows],
        severity_distribution=[{"severity_level": r["severity_level"], "count": r["count"]} for r in severity_rows],
        outbreak_alerts=[
            {
                "keyword": r["keyword"],
                "area": r["area"],
                "recent_count": r["recent_count"],
                "previous_count": r["previous_count"],
                "increase_pct": float(r["increase_pct"]),
            }
            for r in alert_rows
        ],
    )


# ── Triage manual PDF upload ──────────────────────────────────────────────────

async def _run_ingest_task(
    *,
    pool: asyncpg.Pool,
    upload_id: str,
    pdf_path: str,
) -> None:
    """Background task: clear old embeddings, ingest new PDF, update DB record."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from app.services.ai.rag_ingest import ingest_replace

    async with pool.acquire() as conn:
        try:
            loop = asyncio.get_running_loop()
            with ThreadPoolExecutor(max_workers=1) as executor:
                chunks = await loop.run_in_executor(
                    executor,
                    lambda: ingest_replace(pdf_path),
                )
            await conn.execute(
                """UPDATE triage_manual_uploads
                      SET status='ready', chunks_count=$1, completed_at=NOW()
                    WHERE id=$2""",
                chunks,
                upload_id,
            )
            logger.info("Triage manual ingested: %d chunks (upload_id=%s)", chunks, upload_id)
        except Exception as exc:
            logger.exception("Triage manual ingest failed for upload_id=%s", upload_id)
            await conn.execute(
                """UPDATE triage_manual_uploads
                      SET status='failed', error_message=$1, completed_at=NOW()
                    WHERE id=$2""",
                str(exc)[:500],
                upload_id,
            )


@router.post("/admin/triage-manual/upload")
async def upload_triage_manual(
    request: Request,
    file: UploadFile = File(..., description="Hospital triage manual PDF"),
    connection: asyncpg.Connection = Depends(get_connection),
    admin_user: dict = Depends(require_roles("super_admin", "nurse")),
) -> JSONResponse:
    """Upload a new triage manual PDF and trigger background RAG ingestion.

    Replaces any previously uploaded manual.  The old pgvector embeddings are
    deleted automatically before the new ones are stored.

    Returns a JSON object with the upload ``id`` and initial ``status``.
    """
    import os

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    # Save to a fixed path so the RAG ingest script can find it
    save_path = getattr(settings, "triage_manual_path", "app/data/triage_manual.pdf")
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)

    content = await file.read()
    file_size = len(content)

    if file_size == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if file_size > 50 * 1024 * 1024:  # 50 MB guard
        raise HTTPException(status_code=413, detail="File too large (max 50 MB).")

    with open(save_path, "wb") as fh:
        fh.write(content)

    # Insert upload record
    uploader = admin_user.get("email") or admin_user.get("id") or "unknown"
    row = await connection.fetchrow(
        """INSERT INTO triage_manual_uploads
               (original_filename, file_size_bytes, status, uploaded_by)
           VALUES ($1, $2, 'processing', $3)
           RETURNING id, status, uploaded_at""",
        file.filename,
        file_size,
        str(uploader),
    )

    upload_id = str(row["id"])

    # Kick off background ingest (non-blocking)
    pool: asyncpg.Pool = request.app.state.db_pool
    asyncio.create_task(
        _run_ingest_task(pool=pool, upload_id=upload_id, pdf_path=save_path)
    )

    return JSONResponse(
        status_code=202,
        content={
            "id": upload_id,
            "status": "processing",
            "original_filename": file.filename,
            "file_size_bytes": file_size,
            "uploaded_at": row["uploaded_at"].isoformat(),
            "message": "Upload received. Ingestion is running in the background.",
        },
    )


@router.get("/admin/triage-manual/status")
async def get_triage_manual_status(
    connection: asyncpg.Connection = Depends(get_connection),
    admin_user: dict = Depends(require_roles("super_admin", "nurse")),
) -> JSONResponse:
    """Return the latest triage manual upload record.

    The frontend polls this endpoint after uploading to track ingest progress.
    Returns ``null`` when no manual has been uploaded yet.
    """
    row = await connection.fetchrow(
        """SELECT id, original_filename, file_size_bytes, chunks_count,
                  status, error_message, uploaded_by, uploaded_at, completed_at
             FROM triage_manual_uploads
            ORDER BY uploaded_at DESC
            LIMIT 1"""
    )
    if row is None:
        return JSONResponse(content=None)

    return JSONResponse(content={
        "id": str(row["id"]),
        "original_filename": row["original_filename"],
        "file_size_bytes": row["file_size_bytes"],
        "chunks_count": row["chunks_count"],
        "status": row["status"],
        "error_message": row["error_message"],
        "uploaded_by": row["uploaded_by"],
        "uploaded_at": row["uploaded_at"].isoformat() if row["uploaded_at"] else None,
        "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
    })


# ── Screening criteria governance (SRS F31-F35) ───────────────────────────────
#
# Criteria are curated/seeded only (the document-upload extraction path was
# removed by product decision). Lifecycle: draft → head-nurse edit (PUT) →
# submit → approve → activate. Activating retires the current active version
# in the same transaction; activating a retired version is the rollback path.
# Sessions pin the version they started with, so activation never changes an
# in-flight conversation.

# Legacy drafts created by the removed upload path may still carry this
@router.get("/admin/triage-stats", response_model=TriageStatsOut)
async def get_triage_stats(
    days: int = Query(7, ge=1, le=90),
    _admin_user: dict = Depends(require_roles("super_admin", "nurse", "viewer")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Operational numbers behind the nurse and admin dashboards.

    Every series is returned DENSE (generate_series left-joined to the counts)
    so a day or hour with no patients arrives as an explicit zero. The old
    surveillance trend grouped by date and let the client space points by
    index, which drew five empty days as a straight line between two bars.
    """

    queue = await connection.fetchrow(
        """
        SELECT
            COUNT(*) AS pending,
            ROUND(EXTRACT(EPOCH FROM (NOW() - MIN(created_at))) / 60) AS oldest_minutes
        FROM assessment_reviews
        WHERE status = 'pending'
        """
    )

    # Acuity is the engine's own MOPH level, taken from the session it decided
    # on — not from disease_surveillance, whose severity_level is NULL for
    # every row the extractor wrote.
    acuity_rows = await connection.fetch(
        """
        SELECT (metadata->'triage_classification'->>'level')::int AS level,
               COUNT(*) AS count
        FROM sessions
        WHERE started_at >= NOW() - INTERVAL '1 day' * $1
          AND metadata->'triage_classification'->>'level' IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        days,
    )

    hourly_rows = await connection.fetch(
        """
        SELECT h.hour, COALESCE(c.count, 0) AS count
        FROM generate_series(0, 23) AS h(hour)
        LEFT JOIN (
            SELECT EXTRACT(HOUR FROM started_at)::int AS hour, COUNT(*) AS count
            FROM sessions
            WHERE started_at::date = CURRENT_DATE
            GROUP BY 1
        ) c ON c.hour = h.hour
        ORDER BY h.hour
        """
    )

    department_rows = await connection.fetch(
        """
        SELECT d.code, d.name_en, d.name_th, COUNT(*) AS count
        FROM assessment_reviews ar
        JOIN departments d
          ON d.id = COALESCE(ar.confirmed_department_id, ar.proposed_department_id)
        WHERE ar.created_at >= NOW() - INTERVAL '1 day' * $1
        GROUP BY d.code, d.name_en, d.name_th
        ORDER BY count DESC
        """,
        days,
    )

    # How often the nurse kept the engine's department. `corrected` is the
    # disagreement signal — the one number that says whether routing is
    # trustworthy — and nothing computed it before.
    agreement = await connection.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE status IN ('approved', 'corrected')) AS reviewed,
            COUNT(*) FILTER (WHERE status = 'approved') AS confirmed,
            COUNT(*) FILTER (WHERE status = 'corrected') AS rerouted,
            ROUND(
                AVG(EXTRACT(EPOCH FROM (reviewed_at - created_at)) / 60)
                FILTER (WHERE reviewed_at IS NOT NULL)
            ) AS avg_review_minutes
        FROM assessment_reviews
        WHERE created_at >= NOW() - INTERVAL '1 day' * $1
        """,
        days,
    )

    daily_rows = await connection.fetch(
        """
        SELECT d.day::date AS date,
               COALESCE(c.sessions, 0) AS sessions,
               COALESCE(c.screened, 0) AS screened
        FROM generate_series(
            (NOW() - INTERVAL '1 day' * ($1 - 1))::date,
            NOW()::date,
            INTERVAL '1 day'
        ) AS d(day)
        LEFT JOIN (
            SELECT started_at::date AS day,
                   COUNT(*) AS sessions,
                   COUNT(*) FILTER (
                       WHERE metadata->'triage_classification'->>'level' IS NOT NULL
                   ) AS screened
            FROM sessions
            WHERE started_at >= NOW() - INTERVAL '1 day' * $1
            GROUP BY 1
        ) c ON c.day = d.day
        ORDER BY d.day
        """,
        days,
    )

    reviewed = (agreement["reviewed"] if agreement else 0) or 0
    confirmed = (agreement["confirmed"] if agreement else 0) or 0

    return TriageStatsOut(
        days=days,
        pending_reviews=(queue["pending"] if queue else 0) or 0,
        oldest_pending_minutes=(
            int(queue["oldest_minutes"])
            if queue and queue["oldest_minutes"] is not None
            else None
        ),
        acuity=[{"level": r["level"], "count": r["count"]} for r in acuity_rows],
        hourly_today=[{"hour": r["hour"], "count": r["count"]} for r in hourly_rows],
        departments=[
            {
                "code": r["code"],
                "name_en": r["name_en"],
                "name_th": r["name_th"],
                "count": r["count"],
            }
            for r in department_rows
        ],
        agreement={
            "reviewed": reviewed,
            "confirmed": confirmed,
            "rerouted": (agreement["rerouted"] if agreement else 0) or 0,
            # None, not 0, when nothing was reviewed — an empty queue must not
            # render as "0% agreement".
            "agreement_rate": round(confirmed / reviewed, 4) if reviewed else None,
            "avg_review_minutes": (
                int(agreement["avg_review_minutes"])
                if agreement and agreement["avg_review_minutes"] is not None
                else None
            ),
        },
        daily=[
            {
                "date": str(r["date"]),
                "sessions": r["sessions"],
                "screened": r["screened"],
            }
            for r in daily_rows
        ],
    )


@router.get("/admin/ai-metrics")
async def get_ai_metrics(
    date_from: str | None = Query(None, alias="from", description="ISO date/datetime lower bound"),
    date_to: str | None = Query(None, alias="to", description="ISO date/datetime upper bound"),
    _admin_user: dict = Depends(require_roles("super_admin", "nurse", "viewer")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Aggregate AI transparency metrics over ai_inference_audit (SRS F40).

    Feeds the head-nurse governance panel: call volumes/ok-rates/latency per
    LLM call site, dispositions by level and department, validator violation
    counts, and escalation totals.
    """

    def _parse_bound(raw: str | None, name: str):
        if raw is None:
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid {name} datetime: {raw}"
            ) from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    bounds = []
    clauses = []
    lower = _parse_bound(date_from, "from")
    if lower is not None:
        bounds.append(lower)
        clauses.append(f"created_at >= ${len(bounds)}")
    upper = _parse_bound(date_to, "to")
    if upper is not None:
        bounds.append(upper)
        clauses.append(f"created_at <= ${len(bounds)}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    call_sites = await connection.fetch(
        f"""
        SELECT call_site,
               COUNT(*) AS calls,
               COUNT(*) FILTER (WHERE ok) AS ok_calls,
               ROUND(AVG(latency_ms) FILTER (WHERE latency_ms IS NOT NULL)) AS avg_latency_ms
        FROM ai_inference_audit
        {where}
        GROUP BY call_site
        ORDER BY call_site
        """,
        *bounds,
    )
    dispositions = await connection.fetch(
        f"""
        SELECT rules_trace->>'level' AS level,
               rules_trace->>'department_code' AS department_code,
               COUNT(*) AS count
        FROM ai_inference_audit
        {where + (' AND ' if where else 'WHERE ')} call_site = 'disposition'
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        *bounds,
    )
    violations = await connection.fetch(
        f"""
        SELECT violation, COUNT(*) AS count
        FROM ai_inference_audit,
             LATERAL jsonb_array_elements_text(validator_result) AS violation
        {where + (' AND ' if where else 'WHERE ')}
            jsonb_typeof(validator_result) = 'array'
        GROUP BY violation
        ORDER BY count DESC
        """,
        *bounds,
    )
    totals_row = await connection.fetchrow(
        f"""
        SELECT
            COUNT(DISTINCT session_id) AS sessions,
            COUNT(*) FILTER (WHERE call_site = 'escalation') AS escalations,
            COUNT(*) FILTER (WHERE call_site = 'extraction' AND NOT ok) AS extraction_failures,
            COUNT(*) FILTER (WHERE call_site = 'disposition') AS dispositions
        FROM ai_inference_audit
        {where}
        """,
        *bounds,
    )

    # Grounding: how often the patient-facing explanation actually drew on
    # the uploaded triage manual, and why not when it didn't. Lives in the
    # explain entry's rules_trace->'rag' (written by the explain node).
    grounding_row = await connection.fetchrow(
        f"""
        SELECT
            COUNT(*) AS explanations,
            COUNT(*) FILTER (WHERE (rules_trace->'rag'->>'used')::boolean) AS grounded
        FROM ai_inference_audit
        {where + (' AND ' if where else 'WHERE ')} call_site = 'explain'
        """,
        *bounds,
    )
    ungrounded_reasons = await connection.fetch(
        f"""
        SELECT rules_trace->'rag'->>'reason' AS reason, COUNT(*) AS count
        FROM ai_inference_audit
        {where + (' AND ' if where else 'WHERE ')} call_site = 'explain'
            AND NOT COALESCE((rules_trace->'rag'->>'used')::boolean, FALSE)
        GROUP BY 1
        ORDER BY count DESC
        """,
        *bounds,
    )
    explanations = (grounding_row["explanations"] if grounding_row else 0) or 0
    grounded = (grounding_row["grounded"] if grounding_row else 0) or 0

    return {
        "from": lower.isoformat() if lower else None,
        "to": upper.isoformat() if upper else None,
        "totals": dict(totals_row) if totals_row else {},
        "grounding": {
            "explanations": explanations,
            "grounded": grounded,
            "grounded_rate": round(grounded / explanations, 4) if explanations else None,
            "ungrounded_reasons": [
                {"reason": r["reason"] or "unknown", "count": r["count"]}
                for r in ungrounded_reasons
            ],
        },
        "call_sites": [
            {
                "call_site": r["call_site"],
                "calls": r["calls"],
                "ok_calls": r["ok_calls"],
                "ok_rate": round(r["ok_calls"] / r["calls"], 4) if r["calls"] else None,
                "avg_latency_ms": int(r["avg_latency_ms"]) if r["avg_latency_ms"] is not None else None,
            }
            for r in call_sites
        ],
        "dispositions": [
            {
                "level": int(r["level"]) if r["level"] is not None else None,
                "department_code": r["department_code"],
                "count": r["count"],
            }
            for r in dispositions
        ],
        "validator_violations": [
            {"violation": r["violation"], "count": r["count"]} for r in violations
        ],
    }
