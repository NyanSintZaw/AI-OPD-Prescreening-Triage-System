from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any


TOKEN_TTL_HOURS = 12


# Password hashing: stdlib scrypt (memory-hard, no extra dependency).
# n=2**14, r=8 → ~16 MB and ~50 ms per verify, inside OpenSSL's 32 MB default.
# ponytail: that ~50 ms blocks the event loop; move to run_in_executor only if
# login volume ever grows past a handful of staff per shift.
_SCRYPT_PARAMS = (2**14, 8, 1)
_SCRYPT_PREFIX = "scrypt${}${}${}$".format(*_SCRYPT_PARAMS)


def hash_password(password: str) -> str:
    n, r, p = _SCRYPT_PARAMS
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32
    )
    return f"{_SCRYPT_PREFIX}{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Check a password against a stored hash (scrypt, or legacy sha256).

    Legacy unsalted ``sha256$`` hashes still verify so nobody is locked out;
    ``needs_rehash`` tells the login route to replace them in place.
    """
    if stored_hash.startswith("scrypt$"):
        try:
            _, n, r, p, salt_hex, digest_hex = stored_hash.split("$")
            expected = hashlib.scrypt(
                password.encode("utf-8"),
                salt=bytes.fromhex(salt_hex),
                n=int(n),
                r=int(r),
                p=int(p),
                dklen=len(digest_hex) // 2,
            )
        except ValueError:
            return False
        return secrets.compare_digest(expected.hex(), digest_hex)
    if stored_hash.startswith("sha256$"):
        expected = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return secrets.compare_digest(f"sha256${expected}", stored_hash)
    return False


def needs_rehash(stored_hash: str) -> bool:
    """True when the stored hash is legacy or uses outdated scrypt params."""
    return not stored_hash.startswith(_SCRYPT_PREFIX)


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
