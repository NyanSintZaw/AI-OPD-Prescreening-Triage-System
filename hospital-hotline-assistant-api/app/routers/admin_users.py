import logging
from uuid import UUID
import asyncpg
from fastapi import (
    Depends,
    HTTPException,
    Request,
    status,
)
from app.database import get_connection
from app.services.admin_auth import (
    hash_password_sha256,
    issue_admin_token,
    verify_password,
)

logger = logging.getLogger(__name__)
from app.schemas import (
    AdminLoginRequest,
    AdminLoginResponse,
    AdminUserCreate,
    AdminUserManageOut,
    AdminUserUpdate,
    AdminUserOut,
)

from fastapi import APIRouter
from app.routers.deps import require_roles

router = APIRouter()

@router.post("/admin/login", response_model=AdminLoginResponse)
async def admin_login(
    payload: AdminLoginRequest,
    request: Request,
    connection: asyncpg.Connection = Depends(get_connection),
):
    user = await connection.fetchrow(
        """
        SELECT id, email, password_hash, full_name, role, is_active
        FROM admin_users
        WHERE LOWER(email) = LOWER($1)
        """,
        payload.email,
    )
    if user is None or not user["is_active"]:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token, expires_at = issue_admin_token(
        request.app.state.admin_tokens,
        admin_user_id=str(user["id"]),
        email=user["email"],
        role=user["role"],
    )
    await connection.execute(
        "UPDATE admin_users SET last_login_at = NOW() WHERE id = $1",
        user["id"],
    )
    return AdminLoginResponse(
        access_token=token,
        expires_at=expires_at,
        user=AdminUserOut(
            id=user["id"],
            email=user["email"],
            full_name=user["full_name"],
            role=user["role"],
        ),
    )


# ── Nurse account management (admin → User Settings) ────────────────────────
# Nurses ARE admin_users rows with role 'admin' (the /nurse portal role).
# Only those rows are manageable here — super_admin/viewer accounts are not
# touchable from the UI.

async def _fetch_manageable_user(
    connection: asyncpg.Connection, user_id: UUID
) -> asyncpg.Record:
    row = await connection.fetchrow(
        "SELECT * FROM admin_users WHERE id = $1", user_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    if row["role"] != "admin":
        raise HTTPException(
            status_code=403, detail="Only nurse accounts can be managed here"
        )
    return row


def _manage_user_out(row: asyncpg.Record) -> AdminUserManageOut:
    return AdminUserManageOut(
        id=row["id"],
        email=row["email"],
        full_name=row["full_name"],
        role=row["role"],
        is_active=row["is_active"],
        last_login_at=row["last_login_at"],
        created_at=row["created_at"],
    )


@router.get("/admin/users", response_model=list[AdminUserManageOut])
async def admin_list_users(
    connection: asyncpg.Connection = Depends(get_connection),
    _admin_user: dict = Depends(require_roles("super_admin")),
):
    rows = await connection.fetch(
        """
        SELECT * FROM admin_users
        WHERE role = 'admin'
        ORDER BY created_at DESC
        """
    )
    return [_manage_user_out(row) for row in rows]


@router.post(
    "/admin/users",
    response_model=AdminUserManageOut,
    status_code=status.HTTP_201_CREATED,
)
async def admin_create_user(
    payload: AdminUserCreate,
    connection: asyncpg.Connection = Depends(get_connection),
    _admin_user: dict = Depends(require_roles("super_admin")),
):
    email = payload.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="Invalid email address")
    existing = await connection.fetchval(
        "SELECT 1 FROM admin_users WHERE LOWER(email) = $1", email
    )
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    row = await connection.fetchrow(
        """
        INSERT INTO admin_users (email, password_hash, full_name, role, is_active)
        VALUES ($1, $2, $3, 'admin', TRUE)
        RETURNING *
        """,
        email,
        hash_password_sha256(payload.password),
        payload.full_name.strip(),
    )
    return _manage_user_out(row)


@router.patch("/admin/users/{user_id}", response_model=AdminUserManageOut)
async def admin_update_user(
    user_id: UUID,
    payload: AdminUserUpdate,
    connection: asyncpg.Connection = Depends(get_connection),
    _admin_user: dict = Depends(require_roles("super_admin")),
):
    await _fetch_manageable_user(connection, user_id)
    row = await connection.fetchrow(
        """
        UPDATE admin_users SET
            full_name = COALESCE($2, full_name),
            password_hash = COALESCE($3, password_hash),
            is_active = COALESCE($4, is_active),
            updated_at = NOW()
        WHERE id = $1
        RETURNING *
        """,
        user_id,
        payload.full_name.strip() if payload.full_name else None,
        hash_password_sha256(payload.password) if payload.password else None,
        payload.is_active,
    )
    return _manage_user_out(row)


@router.delete("/admin/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_user(
    user_id: UUID,
    connection: asyncpg.Connection = Depends(get_connection),
    _admin_user: dict = Depends(require_roles("super_admin")),
):
    """Hard delete a nurse account. Review history survives — reviewer FKs
    are ON DELETE SET NULL, so signed reviews just show a blank reviewer."""
    await _fetch_manageable_user(connection, user_id)
    await connection.execute("DELETE FROM admin_users WHERE id = $1", user_id)

