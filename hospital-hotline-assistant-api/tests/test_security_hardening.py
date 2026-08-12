"""Security regressions: unauthenticated VN lookup, password hashing, rate limits.

A — GET /sessions/by-visit/{vn} is unauthenticated and a VN is guessable, so
    its response must carry nothing but what the kiosk resume screen renders.
B — passwords are scrypt-hashed; legacy unsalted sha256 rows still verify and
    are upgraded on the next successful login.
C — login and the VN endpoints are rate limited per IP.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.routers.sessions import get_session_by_visit
from app.services.admin_auth import (
    hash_password,
    needs_rehash,
    verify_password,
)
from app.services.rate_limit import rate_limit


# ── A. unauthenticated by-visit lookup ─────────────────────────────────────

SENSITIVE_ROW = {
    "id": uuid4(),
    "status": "active",
    "language": "th",
    "started_at": datetime.now(timezone.utc),
    "ended_at": None,
    "user_agent": "Mozilla/5.0 kiosk-1",
    "ip_hash": "abc123",
    "metadata": {
        "visit": {
            "visit_id": "990000000000000001",
            "patient_name": "สมชาย ใจดี",
            "hn": "09900001",
            "birthdate": "1985-03-12",
            "name_confirmed": True,
        },
        "vitals": {"systolic": 158, "diastolic": 94},
        "slip_code": "MCH-582A-A528",
        "patient_history": {
            "allergies": "Penicillin",
            "chronic_conditions": "Hypertension (diagnosed 2019)",
            "is_first_time": False,
        },
    },
}


class _FakeConnection:
    def __init__(self, row):
        self.row = row

    async def fetchrow(self, sql: str, *args):
        return self.row


async def test_by_visit_returns_only_kiosk_fields_no_health_data():
    out = await get_session_by_visit("990000000000000001", _FakeConnection(SENSITIVE_ROW))

    # What the kiosk needs to offer continue / start over.
    assert out.found is True
    assert out.session is not None
    assert out.session.id == SENSITIVE_ROW["id"]
    assert out.session.language == "th"
    assert out.status == "active"
    assert out.patient_name == "สมชาย ใจดี"
    assert out.name_confirmed is True

    # Everything else is sensitive personal data under PDPA and must be gone.
    assert out.session.metadata == {}
    assert out.session.user_agent is None
    assert out.session.ip_hash is None
    body = out.model_dump_json()
    for leaked in (
        "09900001",
        "1985-03-12",
        "Penicillin",
        "Hypertension",
        "158",
        "MCH-582A-A528",
    ):
        assert leaked not in body, f"{leaked} leaked from an unauthenticated lookup"


async def test_by_visit_not_found_is_empty():
    out = await get_session_by_visit("990000000000000099", _FakeConnection(None))
    assert out.found is False
    assert out.session is None
    assert out.patient_name is None


# ── B. password hashing ────────────────────────────────────────────────────


def test_scrypt_hash_is_salted_and_verifies():
    a = hash_password("s3cret-pw")
    b = hash_password("s3cret-pw")
    assert a.startswith("scrypt$16384$8$1$")
    assert a != b, "same password must not produce the same hash (salt)"
    assert verify_password("s3cret-pw", a)
    assert verify_password("s3cret-pw", b)
    assert not verify_password("wrong-pw", a)
    assert not needs_rehash(a)


def test_legacy_sha256_still_verifies_but_needs_rehash():
    import hashlib

    legacy = "sha256$" + hashlib.sha256(b"old-pw").hexdigest()
    assert verify_password("old-pw", legacy)
    assert not verify_password("nope", legacy)
    assert needs_rehash(legacy), "legacy hash must be upgraded on next login"


def test_malformed_hashes_never_authenticate():
    for junk in ("", "plaintext", "scrypt$", "scrypt$16384$8$1$zz$zz", "md5$abc"):
        assert not verify_password("anything", junk)


async def test_login_upgrades_legacy_hash_in_place():
    """A successful login on a sha256 row rewrites it as scrypt."""
    import hashlib
    from types import SimpleNamespace

    from app.routers.admin_users import admin_login
    from app.schemas import AdminLoginRequest

    user_id = uuid4()
    stored = {
        "id": user_id,
        "email": "nurse@mfu.local",
        "password_hash": "sha256$" + hashlib.sha256(b"old-pw").hexdigest(),
        "full_name": "Nurse",
        "role": "nurse",
        "is_active": True,
    }

    class _Conn:
        def __init__(self):
            self.executed = []

        async def fetchrow(self, sql, *args):
            return stored

        async def execute(self, sql, *args):
            self.executed.append((sql, args))

    conn = _Conn()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(admin_tokens={})))
    resp = await admin_login(
        AdminLoginRequest(email="nurse@mfu.local", password="old-pw"),
        request,  # type: ignore[arg-type]
        conn,  # type: ignore[arg-type]
    )
    assert resp.access_token
    (_sql, args) = conn.executed[0]
    assert args[0] == user_id
    assert isinstance(args[1], str) and args[1].startswith("scrypt$")
    assert verify_password("old-pw", args[1])

    # Already-modern hash → nothing to rewrite (COALESCE keeps the old value).
    stored["password_hash"] = hash_password("old-pw")
    conn2 = _Conn()
    await admin_login(
        AdminLoginRequest(email="nurse@mfu.local", password="old-pw"),
        request,  # type: ignore[arg-type]
        conn2,  # type: ignore[arg-type]
    )
    assert conn2.executed[0][1][1] is None


# ── C. rate limiting ───────────────────────────────────────────────────────


def _request(ip: str):
    from types import SimpleNamespace

    return SimpleNamespace(client=SimpleNamespace(host=ip))


async def test_rate_limit_blocks_after_limit_and_is_per_ip():
    check = rate_limit(f"test_{uuid4()}", limit=3, window_seconds=60)
    for _ in range(3):
        await check(_request("10.0.0.1"))  # type: ignore[arg-type]
    with pytest.raises(HTTPException) as exc:
        await check(_request("10.0.0.1"))  # type: ignore[arg-type]
    assert exc.value.status_code == 429
    assert exc.value.headers is not None and "Retry-After" in exc.value.headers

    # A different client is unaffected.
    await check(_request("10.0.0.2"))  # type: ignore[arg-type]


async def test_rate_limit_window_expires():
    check = rate_limit(f"test_{uuid4()}", limit=1, window_seconds=0.05)
    import asyncio

    await check(_request("10.0.0.3"))  # type: ignore[arg-type]
    with pytest.raises(HTTPException):
        await check(_request("10.0.0.3"))  # type: ignore[arg-type]
    await asyncio.sleep(0.06)
    await check(_request("10.0.0.3"))  # type: ignore[arg-type]


def test_login_and_visit_endpoints_declare_rate_limits():
    """The limiter is only useful if it is actually wired to the routes."""
    from app.main import app

    limited = {
        route.path
        for route in app.routes
        if any(
            getattr(dep.dependency, "__qualname__", "").startswith("rate_limit")
            for dep in getattr(route, "dependencies", [])
        )
    }
    assert {"/admin/login", "/sessions/by-visit/{visit_id}"} <= limited
    assert "/sessions/{session_id}/link-visit" in limited
