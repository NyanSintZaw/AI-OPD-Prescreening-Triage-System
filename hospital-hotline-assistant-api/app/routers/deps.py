import logging
import asyncpg
import httpx
from fastapi import (
    Depends,
    HTTPException,
    Request,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.config import settings
from app.database import get_connection
from app.services.admin_auth import (
    validate_admin_token,
)

logger = logging.getLogger(__name__)

auth_scheme = HTTPBearer(auto_error=False)


async def get_current_admin_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
    connection: asyncpg.Connection = Depends(get_connection),
) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing admin bearer token")
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid auth scheme")

    token_store: dict = request.app.state.admin_tokens
    session = validate_admin_token(token_store, credentials.credentials)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_row = await connection.fetchrow(
        """
        SELECT id, email, full_name, role, is_active
        FROM admin_users
        WHERE id = $1
        """,
        session["admin_user_id"],
    )
    if user_row is None or not user_row["is_active"]:
        raise HTTPException(status_code=401, detail="Admin user is inactive")
    return dict(user_row)


def require_roles(*allowed_roles: str):
    async def _check(admin_user: dict = Depends(get_current_admin_user)) -> dict:
        if admin_user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for this portal",
            )
        return admin_user

    return _check


async def _his_proxy_get(path: str) -> dict | None:
    from app.services.screening.his import his_auth_headers

    if settings.his_mode != "http" or not settings.his_base_url:
        return None
    headers = his_auth_headers(settings.his_api_key)
    url = f"{settings.his_base_url.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=settings.his_timeout_seconds) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Visit not found in HIS")
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        logger.warning("HIS proxy GET %s failed: %s", path, exc)
    return None

