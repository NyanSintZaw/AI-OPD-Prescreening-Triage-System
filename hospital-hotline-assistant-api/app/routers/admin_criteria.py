import json
import logging
from uuid import UUID
import asyncpg
from fastapi import (
    Body,
    Depends,
    HTTPException,
    Query,
)
from app.database import get_connection

logger = logging.getLogger(__name__)

from fastapi import APIRouter
from app.routers.deps import require_roles

router = APIRouter()

_CRITERIA_PROCESSING_PREFIX = "Extracting"


def _jsonb(value):
    """asyncpg returns JSONB as str unless a codec is registered."""
    return json.loads(value) if isinstance(value, str) else value


def _criteria_version_summary(row) -> dict:
    change_summary = row["change_summary"] or ""
    return {
        "id": str(row["id"]),
        "version_no": row["version_no"],
        "status": row["status"],
        "change_summary": change_summary,
        "processing": change_summary.startswith(_CRITERIA_PROCESSING_PREFIX),
        "uploaded_by": row["uploaded_by"],
        "reviewed_by": row["reviewed_by"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "reviewed_at": row["reviewed_at"].isoformat() if row["reviewed_at"] else None,
        "activated_at": row["activated_at"].isoformat() if row["activated_at"] else None,
    }


async def _active_criteria_payload(conn: asyncpg.Connection) -> dict:
    """Raw payload of the active version, or the bundled seed on a fresh DB."""
    row = await conn.fetchrow(
        "SELECT criteria FROM screening_criteria_versions WHERE status = 'active'"
    )
    if row is not None:
        return _jsonb(row["criteria"])
    from app.services.screening.rules.criteria_store import SEED_CRITERIA_PATH

    return json.loads(SEED_CRITERIA_PATH.read_text(encoding="utf-8"))


@router.get("/admin/criteria/active")
async def get_active_criteria_view(
    _admin_user: dict = Depends(require_roles("super_admin", "nurse", "viewer")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Nurse-readable read model of the criteria the booth is deciding with.

    Same document as ``/versions/{id}``, minus the AST: conditions come back
    rendered as text in both languages, rules carry their manual citation, and
    clauses awaiting hospital sign-off are flagged ``placeholder``.
    """
    from app.services.criteria_view import build_criteria_view

    row = await connection.fetchrow(
        """
        SELECT id, version_no, status, change_summary, activated_at, criteria
        FROM screening_criteria_versions WHERE status = 'active'
        """
    )
    if row is None:
        # Fresh DB: the engine falls back to the bundled seed, so show that.
        meta = {
            "id": None, "version_no": None, "status": "seed",
            "change_summary": "", "activated_at": None,
        }
        payload = await _active_criteria_payload(connection)
    else:
        meta = {
            "id": str(row["id"]),
            "version_no": row["version_no"],
            "status": row["status"],
            "change_summary": row["change_summary"] or "",
            "activated_at": row["activated_at"].isoformat() if row["activated_at"] else None,
        }
        payload = _jsonb(row["criteria"])
    return build_criteria_view(payload, meta)


@router.get("/admin/criteria/versions")
async def list_criteria_versions(
    _admin_user: dict = Depends(require_roles("super_admin", "nurse", "viewer")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    rows = await connection.fetch(
        """
        SELECT id, version_no, status, change_summary, uploaded_by, reviewed_by,
               created_at, reviewed_at, activated_at
        FROM screening_criteria_versions
        ORDER BY version_no DESC
        """
    )
    return [_criteria_version_summary(row) for row in rows]


@router.get("/admin/criteria/versions/{version_id}")
async def get_criteria_version_detail(
    version_id: UUID,
    _admin_user: dict = Depends(require_roles("super_admin", "nurse", "viewer")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    from app.services.screening.rules.criteria_store import validation_errors

    row = await connection.fetchrow(
        "SELECT * FROM screening_criteria_versions WHERE id = $1", version_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Criteria version not found")
    payload = _jsonb(row["criteria"])
    result = _criteria_version_summary(row)
    result["criteria"] = payload
    result["validation_errors"] = validation_errors(payload)
    return result


@router.get("/admin/criteria/versions/{version_id}/diff")
async def diff_criteria_version(
    version_id: UUID,
    against: UUID | None = Query(
        None, description="Version to compare against (default: the active version)"
    ),
    _admin_user: dict = Depends(require_roles("super_admin", "nurse", "viewer")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Section-level diff (added/removed/changed rule ids) vs another version."""
    from app.services.screening.rules.criteria_store import diff_criteria

    row = await connection.fetchrow(
        "SELECT criteria FROM screening_criteria_versions WHERE id = $1", version_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Criteria version not found")

    if against is not None:
        base_row = await connection.fetchrow(
            "SELECT id, criteria FROM screening_criteria_versions WHERE id = $1",
            against,
        )
        if base_row is None:
            raise HTTPException(status_code=404, detail="Comparison version not found")
        base_payload = _jsonb(base_row["criteria"])
        base_id = str(base_row["id"])
    else:
        base_payload = await _active_criteria_payload(connection)
        base_id = "active"

    return {
        "version_id": str(version_id),
        "against": base_id,
        "diff": diff_criteria(base_payload, _jsonb(row["criteria"])),
    }


@router.put("/admin/criteria/versions/{version_id}")
async def edit_criteria_version(
    version_id: UUID,
    criteria: dict = Body(..., description="Full criteria JSON document"),
    _admin_user: dict = Depends(require_roles("super_admin", "nurse")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Replace a draft's criteria JSON (the pressure valve for imperfect extraction).

    Saves even when the document has validation errors — they are returned so
    the editor can fix them iteratively — but submit/activate require a clean
    document.
    """
    from app.services.screening.rules.criteria_store import validation_errors

    row = await connection.fetchrow(
        "SELECT status FROM screening_criteria_versions WHERE id = $1", version_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Criteria version not found")
    if row["status"] not in ("draft", "pending_review"):
        raise HTTPException(
            status_code=409,
            detail=f"Only draft/pending_review versions are editable (status: {row['status']})",
        )

    await connection.execute(
        "UPDATE screening_criteria_versions SET criteria = $1::jsonb WHERE id = $2",
        json.dumps(criteria, ensure_ascii=False),
        version_id,
    )
    errors = validation_errors(criteria)
    return {"id": str(version_id), "saved": True, "validation_errors": errors}


async def _criteria_status_transition(
    connection: asyncpg.Connection,
    version_id: UUID,
    *,
    from_statuses: tuple[str, ...],
    to_status: str,
    reviewer: str | None = None,
) -> dict:
    row = await connection.fetchrow(
        "SELECT status, criteria FROM screening_criteria_versions WHERE id = $1",
        version_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Criteria version not found")
    if row["status"] not in from_statuses:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot move {row['status']} → {to_status}; "
                   f"requires status in {list(from_statuses)}",
        )

    from app.services.screening.rules.criteria_store import validation_errors

    errors = validation_errors(_jsonb(row["criteria"]))
    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "Criteria document is invalid", "errors": errors[:20]},
        )

    if to_status == "active":
        async with connection.transaction():
            await connection.execute(
                """UPDATE screening_criteria_versions
                      SET status = 'retired' WHERE status = 'active'"""
            )
            await connection.execute(
                """UPDATE screening_criteria_versions
                      SET status = 'active', activated_at = NOW() WHERE id = $1""",
                version_id,
            )
    elif reviewer is not None:
        await connection.execute(
            """UPDATE screening_criteria_versions
                  SET status = $1, reviewed_by = $2, reviewed_at = NOW()
                WHERE id = $3""",
            to_status,
            reviewer,
            version_id,
        )
    else:
        await connection.execute(
            "UPDATE screening_criteria_versions SET status = $1 WHERE id = $2",
            to_status,
            version_id,
        )
    return {"id": str(version_id), "status": to_status}


@router.post("/admin/criteria/versions/{version_id}/submit")
async def submit_criteria_version(
    version_id: UUID,
    _admin_user: dict = Depends(require_roles("super_admin", "nurse")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    return await _criteria_status_transition(
        connection, version_id, from_statuses=("draft",), to_status="pending_review"
    )


@router.post("/admin/criteria/versions/{version_id}/approve")
async def approve_criteria_version(
    version_id: UUID,
    admin_user: dict = Depends(require_roles("super_admin", "nurse")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    reviewer = str(admin_user.get("email") or admin_user.get("id") or "unknown")
    return await _criteria_status_transition(
        connection,
        version_id,
        from_statuses=("pending_review",),
        to_status="approved",
        reviewer=reviewer,
    )


@router.post("/admin/criteria/versions/{version_id}/activate")
async def activate_criteria_version(
    version_id: UUID,
    _admin_user: dict = Depends(require_roles("super_admin", "nurse")),
    connection: asyncpg.Connection = Depends(get_connection),
):
    """Activate an approved version. Activating a retired version = rollback."""
    return await _criteria_status_transition(
        connection,
        version_id,
        from_statuses=("approved", "retired"),
        to_status="active",
    )

