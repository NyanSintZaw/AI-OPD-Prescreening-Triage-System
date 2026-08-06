"""Guards on PUT /admin/his/connection.

The load-bearing one is `test_host_change_without_token_makes_no_request`:
before this guard existed, an admin could change ONLY the endpoint URL and we
would probe the new host carrying the saved hospital token — a one-field
credential leak.
"""
import pytest
from fastapi import HTTPException

from app.config import settings
from app.routers import admin_his
from app.schemas import HisConnectionUpdate


class _FakeState:
    his_adapter = None


class _FakeApp:
    state = _FakeState()


class _FakeRequest:
    app = _FakeApp()


@pytest.fixture(autouse=True)
def _restore_settings():
    saved = (
        settings.environment,
        settings.his_base_url,
        settings.his_api_key,
        settings.his_mode,
        settings.his_display_name,
    )
    yield
    (
        settings.environment,
        settings.his_base_url,
        settings.his_api_key,
        settings.his_mode,
        settings.his_display_name,
    ) = saved


@pytest.fixture(autouse=True)
def _no_env_writes(monkeypatch):
    """`admin_his_connect` imports `persist_env_keys` INSIDE the function, so it
    must be patched on its own module — patching `admin_his` does nothing and
    the success-path tests would rewrite the developer's real .env (they did,
    once)."""
    import app.services.env_persist as env_persist

    written: list[dict] = []
    monkeypatch.setattr(env_persist, "persist_env_keys", written.append)
    return written


async def _connect(endpoint: str, api_key: str | None = None):
    return await admin_his.admin_his_connect(
        HisConnectionUpdate(name="Hospital", endpoint=endpoint, api_key=api_key),
        _FakeRequest(),  # type: ignore[arg-type]
    )


async def test_host_change_without_token_makes_no_request(monkeypatch):
    """Changing host with a blank token is rejected BEFORE any probe."""
    settings.environment = "development"
    settings.his_base_url = "https://his.hospital.example"
    settings.his_api_key = "REAL-HOSPITAL-TOKEN"

    probed: list[tuple] = []

    async def _spy(endpoint, api_key=None):
        probed.append((endpoint, api_key))
        return True, 1, None

    monkeypatch.setattr(admin_his, "_probe_his_endpoint", _spy)

    with pytest.raises(HTTPException) as exc:
        await _connect("https://attacker.example")
    assert exc.value.status_code == 422
    # The point of the guard: the token never left the process.
    assert probed == []


async def test_same_host_keeps_saved_token(monkeypatch):
    """A path/scheme edit on the same host stays frictionless."""
    settings.environment = "development"
    settings.his_base_url = "https://his.hospital.example"
    settings.his_api_key = "REAL-HOSPITAL-TOKEN"

    probed: list[tuple] = []

    async def _spy(endpoint, api_key=None):
        probed.append((endpoint, api_key))
        return True, 1, None

    monkeypatch.setattr(admin_his, "_probe_his_endpoint", _spy)

    await _connect("https://his.hospital.example/api")
    assert probed == [("https://his.hospital.example/api", "REAL-HOSPITAL-TOKEN")]


async def test_new_host_with_explicit_token_is_allowed(monkeypatch):
    settings.environment = "development"
    settings.his_base_url = "https://his.hospital.example"
    settings.his_api_key = "REAL-HOSPITAL-TOKEN"

    probed: list[tuple] = []

    async def _spy(endpoint, api_key=None):
        probed.append((endpoint, api_key))
        return True, 1, None

    monkeypatch.setattr(admin_his, "_probe_his_endpoint", _spy)
    await _connect("https://uat.hospital.example", api_key="UAT-TOKEN")
    assert probed == [("https://uat.hospital.example", "UAT-TOKEN")]


async def test_plain_http_rejected_outside_development():
    settings.environment = "production"
    settings.his_base_url = None
    settings.his_api_key = None
    with pytest.raises(HTTPException) as exc:
        await _connect("http://his.hospital.example")
    assert exc.value.status_code == 422
    assert "https" in str(exc.value.detail)


async def test_plain_http_allowed_in_development(monkeypatch):
    """The local mock HIS runs on plain http — dev must keep working."""
    settings.environment = "development"
    settings.his_base_url = None
    settings.his_api_key = None

    async def _ok(endpoint, api_key=None):
        return True, 1, None

    monkeypatch.setattr(admin_his, "_probe_his_endpoint", _ok)
    result = await _connect("http://localhost:8001")
    assert result.connected is True
