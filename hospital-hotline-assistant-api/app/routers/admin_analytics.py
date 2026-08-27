import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
import asyncpg
from fastapi import (
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, JSONResponse
from app.config import settings
from app.database import get_connection, records_to_dicts

logger = logging.getLogger(__name__)
from app.schemas import (
    AdminSessionCounts,
    AdminSessionRow,
    AdminSessionsOut,
    SurveillanceSummaryOut,
    TriageStatsOut,
)

from fastapi import APIRouter
from app.routers.deps import require_roles

router = APIRouter()

# ── Admin session log ─────────────────────────────────────────────────────────
#
# The nurse queue answers "is this patient routed right"; this answers "did the
# booth work". Everything here is operational — outcome, turns, latency, vitals
# coverage, criteria version, HIS write-back, engine errors — and the acuity it
# shows is the engine's own MOPH level, never the emergency/urgent/general
# buckets, which are the patient-facing redaction and were never a staff fact.

# Window → the lower bound on started_at. Whitelisted: the value is inlined
# into SQL, so it must never come from the request unchecked.
_SESSION_WINDOWS: dict[str, str | None] = {
    "today": "date_trunc('day', NOW())",
    "7d": "NOW() - INTERVAL '7 days'",
    "30d": "NOW() - INTERVAL '30 days'",
    "all": None,
}

# A session with no disposition and no activity for this long is not "active",
# whatever its status column says — nothing ever closes a walked-away booth
# session, which is why the old table showed four-day-old rows as Active.
_IDLE_MINUTES = 30

_ENRICHED_SQL = """
WITH scoped AS (
    SELECT s.id,
           s.language,
           s.status,
           s.started_at,
           s.ended_at,
           (s.metadata->'triage_classification'->>'level')::int AS triage_level,
           NULLIF(s.metadata->'patient'->>'hn', '')             AS patient_hn,
           s.metadata->'his_prescreen'->>'status'               AS his_status
    FROM sessions s
    {window_clause}
), enriched AS (
    SELECT sc.id AS session_id,
           sc.language,
           sc.status,
           sc.started_at,
           sc.ended_at,
           sc.triage_level,
           sc.patient_hn,
           sc.his_status,
           COALESCE(msg.turns, 0)::int AS turns,
           msg.avg_latency_ms::int     AS avg_latency_ms,
           GREATEST(
               0,
               ROUND(EXTRACT(EPOCH FROM (
                   COALESCE(sc.ended_at, msg.last_at, sc.started_at) - sc.started_at
               )))
           )::int AS duration_seconds,
           rev.status AS review_status,
           pd.name_en AS proposed_department_en,
           pd.name_th AS proposed_department_th,
           cd.name_en AS confirmed_department_en,
           cd.name_th AS confirmed_department_th,
           (
               SELECT COUNT(*)
               FROM jsonb_each(COALESCE(ss.state->'measured_vitals', '{{}}'::jsonb)) AS kv
               -- The vitals the booth ALWAYS takes: cuff, thermometer, and
               -- the pulse the cuff reports. RR has no instrument here and is
               -- never measured, and SpO2 is taken only when a case calls for
               -- it — counting either as core made every complete screening
               -- report itself short.
               WHERE kv.key IN ('hr', 'temp', 'sbp')
                 AND kv.value <> 'null'::jsonb
           )::int AS vitals_measured,
           cv.version_no AS criteria_version,
           COALESCE(err.bad, 0) > 0 AS ai_error,
           CASE
               WHEN sc.triage_level IS NOT NULL THEN 'disposed'
               WHEN sc.status <> 'active'
                 OR COALESCE(msg.last_at, sc.started_at)
                      < NOW() - INTERVAL '{idle} minutes' THEN 'abandoned'
               ELSE 'active'
           END AS outcome
    FROM scoped sc
    LEFT JOIN LATERAL (
        SELECT COUNT(*) FILTER (WHERE m.role = 'user') AS turns,
               MAX(m.created_at) AS last_at,
               ROUND(AVG(m.response_latency_ms)
                     FILTER (WHERE m.response_latency_ms IS NOT NULL)) AS avg_latency_ms
        FROM messages m WHERE m.session_id = sc.id
    ) msg ON TRUE
    LEFT JOIN LATERAL (
        SELECT ar.status, ar.proposed_department_id, ar.confirmed_department_id
        FROM assessment_reviews ar
        WHERE ar.session_id = sc.id
        ORDER BY ar.created_at DESC
        LIMIT 1
    ) rev ON TRUE
    LEFT JOIN departments pd ON pd.id = rev.proposed_department_id
    LEFT JOIN departments cd ON cd.id = rev.confirmed_department_id
    LEFT JOIN screening_sessions ss ON ss.session_id = sc.id
    LEFT JOIN screening_criteria_versions cv ON cv.id = ss.criteria_version_id
    LEFT JOIN LATERAL (
        SELECT COUNT(*) AS bad
        FROM ai_inference_audit a
        WHERE a.session_id = sc.id AND NOT a.ok
    ) err ON TRUE
)
"""


def _enriched_cte(window: str) -> str:
    bound = _SESSION_WINDOWS[window]
    return _ENRICHED_SQL.format(
        window_clause=f"WHERE s.started_at >= {bound}" if bound else "",
        idle=_IDLE_MINUTES,
    )


def _parse_window_bound(raw: str | None, name: str, *, end_of_day: bool = False) -> datetime | None:
    """One ISO bound off the query string, as an aware UTC datetime.

    Shared by `/admin/triage-stats` and `/admin/ai-metrics` so the dashboard's
    calendar means the same thing on both. A naive string is read as UTC rather
    than rejected: the client sends a plain `YYYY-MM-DD` for a whole day and
    should not have to know the server's zone to do it.
    """
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {name} datetime: {raw}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    # A bare `YYYY-MM-DD` upper bound parses to that day's midnight, which would
    # cut the day the user picked down to nothing. Read a date-only `to` as the
    # whole of that day, which is what picking it on a calendar means.
    if end_of_day and len(raw.strip()) <= 10:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed


@router.get("/admin/sessions", response_model=AdminSessionsOut)
async def list_admin_sessions(
    window: Literal["today", "7d", "30d", "all"] = Query("7d"),
    level: str | None = Query(None, description="MOPH level 1-5, or 'none'"),
    outcome: Literal["disposed", "abandoned", "active"] | None = Query(None),
    language: Literal["th", "en"] | None = Query(None),
    flag: Literal["abandoned", "ai_error", "his_failed", "unreviewed"] | None = Query(
        None, description="Ribbon shortcut — the exception the admin clicked"
    ),
    q: str | None = Query(None, max_length=64, description="HN or session-id prefix"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin_user: dict = Depends(require_roles("super_admin", "viewer", "nurse")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    """The admin session log — one page of rows plus the window's exception counts.

    Counts are scoped to the window and NOT to the active filters: clicking
    "14 abandoned" must not zero the other three, or the ribbon stops being a
    map of what is wrong and becomes a readout of what you already selected.
    """

    cte = _enriched_cte(window)

    counts_row = await connection.fetchrow(
        cte
        + """
        SELECT COUNT(*)::int AS sessions,
               COUNT(*) FILTER (WHERE outcome = 'abandoned')::int AS abandoned,
               COUNT(*) FILTER (WHERE ai_error)::int AS ai_errors,
               COUNT(*) FILTER (WHERE his_status = 'failed')::int AS his_failed,
               COUNT(*) FILTER (WHERE review_status = 'pending')::int AS unreviewed
        FROM enriched
        """
    )

    params: list[Any] = []
    clauses: list[str] = []

    def _param(value: Any) -> str:
        params.append(value)
        return f"${len(params)}"

    if level == "none":
        clauses.append("triage_level IS NULL")
    elif level:
        try:
            clauses.append(f"triage_level = {_param(int(level))}")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid level: {level}") from exc
    if outcome:
        clauses.append(f"outcome = {_param(outcome)}")
    if language:
        clauses.append(f"language = {_param(language)}::language_code")
    if flag == "abandoned":
        clauses.append("outcome = 'abandoned'")
    elif flag == "ai_error":
        clauses.append("ai_error")
    elif flag == "his_failed":
        clauses.append("his_status = 'failed'")
    elif flag == "unreviewed":
        clauses.append("review_status = 'pending'")
    if q and q.strip():
        term = _param(f"{q.strip()}%")
        clauses.append(f"(patient_hn ILIKE {term} OR session_id::text ILIKE {term})")

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = await connection.fetch(
        cte
        + f"""
        SELECT *, COUNT(*) OVER ()::int AS total_count
        FROM enriched
        {where}
        ORDER BY started_at DESC
        LIMIT {_param(limit)} OFFSET {_param(offset)}
        """,
        *params,
    )

    dicts = records_to_dicts(rows)
    total = dicts[0].pop("total_count") if dicts else 0
    for row in dicts:
        row.pop("total_count", None)

    return AdminSessionsOut(
        window=window,
        total=total,
        limit=limit,
        offset=offset,
        counts=AdminSessionCounts(**dict(counts_row or {})),
        rows=[AdminSessionRow(**row) for row in dicts],
    )

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


@router.get("/admin/triage-manual/file")
async def get_triage_manual_file(
    admin_user: dict = Depends(require_roles("super_admin", "nurse")),
) -> FileResponse:
    """Serve the triage manual PDF itself.

    The rule book cites this manual as a source but had no way to open it —
    the only routes were upload (POST) and status. `inline` rather than an
    attachment: a nurse checking the manual behind a rule wants to read it in
    a tab, not download a copy. Same roles as /status; this is an internal
    clinical document.
    """
    path = getattr(settings, "triage_manual_path", "app/data/triage_manual.pdf")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="No triage manual has been uploaded.")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=os.path.basename(path),
        content_disposition_type="inline",
    )


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
    days: int = Query(
        7,
        ge=1,
        le=90,
        description="Rolling window in days. Shorthand for from=NOW()-days; ignored when `from` is given.",
    ),
    date_from: str | None = Query(None, alias="from", description="ISO date/datetime lower bound"),
    date_to: str | None = Query(None, alias="to", description="ISO date/datetime upper bound"),
    _admin_user: dict = Depends(require_roles("super_admin", "nurse", "viewer")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Operational numbers behind the nurse and admin dashboards.

    Every series is returned DENSE (generate_series left-joined to the counts)
    so a day or hour with no patients arrives as an explicit zero. The old
    surveillance trend grouped by date and let the client space points by
    index, which drew five empty days as a straight line between two bars.

    The window is either a rolling `days` or an explicit `from`/`to` pair, the
    same contract `/admin/ai-metrics` already used — the dashboard's chips send
    the first, its calendar sends the second. Every series below is bounded by
    the resolved pair, so the two controls cannot disagree about what "the
    period" means. `hourly_today` is the one exception and stays on
    CURRENT_DATE: it answers "who came to the booth today", which a chosen
    window in March should not repoint.
    """

    lower = _parse_window_bound(date_from, "from")
    if lower is None:
        # `days` counts calendar days INCLUDING today, and starts at that day's
        # midnight — so "last 7 days" is seven dated columns, not a rolling
        # 7x24h that drops half of the earliest one.
        start = datetime.now(timezone.utc) - timedelta(days=days - 1)
        lower = start.replace(hour=0, minute=0, second=0, microsecond=0)
    upper = _parse_window_bound(date_to, "to", end_of_day=True) or datetime.now(timezone.utc)
    if upper < lower:
        raise HTTPException(status_code=400, detail="`to` is earlier than `from`.")
    # Reported back so the client can label the period it actually got rather
    # than the one it asked for.
    span_days = max(1, (upper.date() - lower.date()).days + 1)

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
        WHERE started_at >= $1 AND started_at <= $2
          AND metadata->'triage_classification'->>'level' IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        lower,
        upper,
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
        WHERE ar.created_at >= $1 AND ar.created_at <= $2
        GROUP BY d.code, d.name_en, d.name_th
        ORDER BY count DESC
        """,
        lower,
        upper,
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
        WHERE created_at >= $1 AND created_at <= $2
        """,
        lower,
        upper,
    )

    # One row per day, three sources. The review and audit columns exist so the
    # admin tiles can each carry a sparkline: an agreement rate or a latency
    # with no shape behind it is a number nobody can act on.
    daily_rows = await connection.fetch(
        """
        SELECT d.day::date AS date,
               COALESCE(s.sessions, 0) AS sessions,
               COALESCE(s.screened, 0) AS screened,
               COALESCE(r.reviewed, 0) AS reviewed,
               COALESCE(r.rerouted, 0) AS rerouted,
               COALESCE(a.escalated, 0) AS escalated,
               a.avg_latency_ms
        FROM generate_series($1::date, $2::date, INTERVAL '1 day') AS d(day)
        LEFT JOIN (
            SELECT started_at::date AS day,
                   COUNT(*) AS sessions,
                   COUNT(*) FILTER (
                       WHERE metadata->'triage_classification'->>'level' IS NOT NULL
                   ) AS screened
            FROM sessions
            WHERE started_at >= $1 AND started_at <= $2
            GROUP BY 1
        ) s ON s.day = d.day
        LEFT JOIN (
            SELECT created_at::date AS day,
                   COUNT(*) FILTER (WHERE status IN ('approved', 'corrected')) AS reviewed,
                   COUNT(*) FILTER (WHERE status = 'corrected') AS rerouted
            FROM assessment_reviews
            WHERE created_at >= $1 AND created_at <= $2
            GROUP BY 1
        ) r ON r.day = d.day
        LEFT JOIN (
            SELECT created_at::date AS day,
                   COUNT(*) FILTER (WHERE call_site = 'escalation') AS escalated,
                   ROUND(AVG(latency_ms) FILTER (WHERE latency_ms IS NOT NULL)) AS avg_latency_ms
            FROM ai_inference_audit
            WHERE created_at >= $1 AND created_at <= $2
            GROUP BY 1
        ) a ON a.day = d.day
        ORDER BY d.day
        """,
        lower,
        upper,
    )

    # started -> disposed -> reviewed -> pushed to the HIS. Every stage is a
    # subset of the one before it, so a drop between two stages is a loss the
    # admin can go and look at. Nothing computed this before, which is why the
    # dashboard could show "142 screened" and never say how many of them
    # actually reached the hospital system.
    funnel_row = await connection.fetchrow(
        """
        SELECT
            COUNT(*) AS started,
            COUNT(*) FILTER (
                WHERE s.metadata->'triage_classification'->>'level' IS NOT NULL
            ) AS disposed,
            COUNT(*) FILTER (WHERE EXISTS (
                SELECT 1 FROM assessment_reviews ar
                WHERE ar.session_id = s.id AND ar.status IN ('approved', 'corrected')
            )) AS reviewed,
            COUNT(*) FILTER (WHERE s.metadata->'his_prescreen'->>'status' = 'pushed') AS his_pushed,
            COUNT(*) FILTER (WHERE s.metadata->'his_prescreen'->>'status' = 'failed') AS his_failed,
            COUNT(*) FILTER (WHERE s.metadata->'his_prescreen'->>'status' = 'skipped') AS his_skipped
        FROM sessions s
        WHERE s.started_at >= $1 AND started_at <= $2
        """,
        lower,
        upper,
    )

    # Dense 7 x 24. `hourly_today` is the nurse's "how busy am I right now";
    # a staffing decision needs the whole window, and an hour that never sees
    # a patient has to render as an explicit zero cell rather than vanish.
    weekday_rows = await connection.fetch(
        """
        SELECT w.weekday, h.hour, COALESCE(c.count, 0) AS count
        FROM generate_series(0, 6) AS w(weekday)
        CROSS JOIN generate_series(0, 23) AS h(hour)
        LEFT JOIN (
            SELECT EXTRACT(DOW FROM started_at)::int AS weekday,
                   EXTRACT(HOUR FROM started_at)::int AS hour,
                   COUNT(*) AS count
            FROM sessions
            WHERE started_at >= $1 AND started_at <= $2
            GROUP BY 1, 2
        ) c ON c.weekday = w.weekday AND c.hour = h.hour
        ORDER BY w.weekday, h.hour
        """,
        lower,
        upper,
    )

    reviewed = (agreement["reviewed"] if agreement else 0) or 0
    confirmed = (agreement["confirmed"] if agreement else 0) or 0

    return TriageStatsOut(
        days=span_days,
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
                "reviewed": r["reviewed"],
                "rerouted": r["rerouted"],
                "escalated": r["escalated"],
                "avg_latency_ms": (
                    int(r["avg_latency_ms"]) if r["avg_latency_ms"] is not None else None
                ),
            }
            for r in daily_rows
        ],
        funnel=dict(funnel_row) if funnel_row else {},
        weekday_hourly=[
            {"weekday": r["weekday"], "hour": r["hour"], "count": r["count"]}
            for r in weekday_rows
        ],
    )


@router.get("/admin/ai-metrics")
async def get_ai_metrics(
    days: int | None = Query(
        None,
        ge=1,
        le=90,
        description="Rolling window in days. Shorthand for from=NOW()-days; ignored when `from` is given.",
    ),
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

    bounds = []
    clauses = []
    lower = _parse_window_bound(date_from, "from")
    # `days` exists so this endpoint shares the dashboard's one period control
    # with /admin/triage-stats instead of needing its own date pickers. An
    # explicit `from` still wins.
    if lower is None and days is not None:
        lower = datetime.now(timezone.utc) - timedelta(days=days)
    if lower is not None:
        bounds.append(lower)
        clauses.append(f"created_at >= ${len(bounds)}")
    upper = _parse_window_bound(date_to, "to")
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
