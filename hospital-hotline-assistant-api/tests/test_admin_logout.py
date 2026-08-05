"""POST /admin/logout revokes the in-memory token (no DB involved)."""
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.admin_auth import issue_admin_token, validate_admin_token


async def test_admin_logout_revokes_token():
    app.state.admin_tokens = {}
    token, _ = issue_admin_token(
        app.state.admin_tokens, admin_user_id="u1", email="n@x", role="nurse"
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/admin/logout", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 204
        assert validate_admin_token(app.state.admin_tokens, token) is None
        # Idempotent: logging out an already-revoked token is still 204.
        resp = await client.post(
            "/admin/logout", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 204
