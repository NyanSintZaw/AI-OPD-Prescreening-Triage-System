from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any


TOKEN_TTL_HOURS = 12


def hash_password_sha256(password: str) -> str:
    digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return f"sha256${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash.startswith("sha256$"):
        return False
    expected = hash_password_sha256(password)
    return secrets.compare_digest(expected, stored_hash)


def issue_admin_token(
    token_store: dict[str, dict[str, Any]],
    *,
    admin_user_id: str,
    email: str,
    role: str,
) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS)
    token_store[token] = {
        "admin_user_id": admin_user_id,
        "email": email,
        "role": role,
        "expires_at": expires_at,
    }
    return token, expires_at


def validate_admin_token(
    token_store: dict[str, dict[str, Any]], token: str
) -> dict[str, Any] | None:
    session = token_store.get(token)
    if not session:
        return None
    expires_at = session.get("expires_at")
    if not isinstance(expires_at, datetime):
        token_store.pop(token, None)
        return None
    if datetime.now(timezone.utc) >= expires_at:
        token_store.pop(token, None)
        return None
    return session
