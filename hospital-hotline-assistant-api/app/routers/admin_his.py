import logging
from urllib.parse import urlsplit

import httpx
from fastapi import (
    Depends,
    HTTPException,
    Request,
)
from app.config import settings

logger = logging.getLogger(__name__)
from app.schemas import (
    HisConnectionOut,
    HisConnectionUpdate,
)

from fastapi import APIRouter
from app.routers.deps import _his_proxy_get, require_roles

router = APIRouter()

async def _probe_his_endpoint(
    endpoint: str, api_key: str | None = None
) -> tuple[bool, int | None, str | None]:
    """Try the visits listing on a candidate HIS endpoint. Returns
    (connected, visit_count, error_message)."""
    from app.services.screening.his import his_auth_headers

    headers = his_auth_headers(api_key)
    url = f"{endpoint.rstrip('/')}/api/visits"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return False, None, f"Could not reach the database endpoint: {exc}"
    if resp.status_code == 401:
        return False, None, "The database rejected our access token (401)."
    if resp.status_code != 200:
        return False, None, f"The database answered with status {resp.status_code}."
    try:
        visits = resp.json().get("visits", [])
    except ValueError:
        return False, None, "The endpoint did not return the expected data."
    return True, len(visits), None


def _his_connection_payload(
    connected: bool, visit_count: int | None, message: str | None
) -> HisConnectionOut:
    return HisConnectionOut(
        mode="http" if settings.his_mode == "http" else "mock",
        endpoint=settings.his_base_url if settings.his_mode == "http" else None,
        name=settings.his_display_name,
        connected=connected,
        visit_count=visit_count,
        message=message,
        has_api_key=bool(settings.his_api_key),
    )


@router.get("/admin/his/connection", response_model=HisConnectionOut)
async def admin_his_connection(
    _admin_user: dict = Depends(require_roles("super_admin", "nurse", "viewer")),
):
    """Current hospital-DB connection state for the Database Settings tab."""
    if settings.his_mode != "http" or not settings.his_base_url:
        return _his_connection_payload(False, None, None)
    connected, count, message = await _probe_his_endpoint(
        settings.his_base_url, settings.his_api_key
    )
    return _his_connection_payload(connected, count, message)


@router.put("/admin/his/connection", response_model=HisConnectionOut)
async def admin_his_connect(
    payload: HisConnectionUpdate,
    request: Request,
    _admin_user: dict = Depends(require_roles("super_admin")),
):
    """Establish (or change) the hospital-DB connection from the admin page.

    Probes the endpoint first — an unreachable endpoint is rejected without
    saving, so the demo can never end up pointed at a dead database. On
    success the adapter is swapped live (no restart) and the config is
    persisted to .env.
    """
    from app.services.env_persist import persist_env_keys
    from app.services.screening.his import HttpHisAdapter

    endpoint = payload.endpoint.strip().rstrip("/")
    if not endpoint.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=422, detail="Endpoint must start with http:// or https://"
        )
    # Outside development the access token must never cross the wire in clear
    # text. Plain http:// stays allowed in dev so the local mock HIS works.
    if settings.environment != "development" and not endpoint.startswith("https://"):
        raise HTTPException(
            status_code=422,
            detail="Endpoint must use https:// — a plain http:// connection would "
            "send the hospital access token in clear text.",
        )
    # Blank token field keeps the saved one (so admins can change the name or
    # URL without re-typing the secret); disconnect is how you clear it.
    api_key = (payload.api_key or "").strip() or settings.his_api_key
    # ...but only for the SAME host. Reusing the saved token against a new host
    # would let anyone who can edit this form point us at a server they control
    # and have us hand over the hospital's token during the probe below — so
    # reject before any outbound request is made.
    if not (payload.api_key or "").strip():
        new_host = urlsplit(endpoint).netloc.lower()
        saved_host = urlsplit(settings.his_base_url or "").netloc.lower()
        if api_key and new_host != saved_host:
            raise HTTPException(
                status_code=422,
                detail="Re-enter the access token when changing the hospital host.",
            )
    connected, count, message = await _probe_his_endpoint(endpoint, api_key)
    if not connected:
        raise HTTPException(status_code=422, detail=message or "Connection failed")

    settings.his_mode = "http"
    settings.his_base_url = endpoint
    settings.his_api_key = api_key
    settings.his_display_name = payload.name.strip()
    request.app.state.his_adapter = HttpHisAdapter(
        base_url=endpoint,
        api_key=api_key,
        timeout=settings.his_timeout_seconds,
    )
    try:
        persist_env_keys({
            "HIS_MODE": "http",
            "HIS_BASE_URL": endpoint,
            "HIS_API_KEY": api_key or "",
            "HIS_DISPLAY_NAME": settings.his_display_name,
        })
    except OSError:
        logger.exception("HIS connection applied but failed to persist .env")
    logger.info(
        "HIS connection established by admin: %s (%s)", endpoint, settings.his_display_name
    )
    return _his_connection_payload(True, count, None)


@router.delete("/admin/his/connection", response_model=HisConnectionOut)
async def admin_his_disconnect(
    request: Request,
    _admin_user: dict = Depends(require_roles("super_admin")),
):
    """Disconnect the hospital DB: back to the mock adapter, persisted.

    HIS_BASE_URL is kept in .env so reconnecting pre-fills the last endpoint;
    the access token is cleared (re-typed on reconnect — it's a secret, and
    this is the UI's only way to drop a stale one). Booth flows keep working
    (mock accepts every visit, write-backs are logged instead of sent)."""
    from app.services.env_persist import persist_env_keys
    from app.services.screening.his import MockHisAdapter

    settings.his_mode = "mock"
    settings.his_api_key = None
    request.app.state.his_adapter = MockHisAdapter()
    try:
        persist_env_keys({"HIS_MODE": "mock", "HIS_API_KEY": ""})
    except OSError:
        logger.exception("HIS disconnect applied but failed to persist .env")
    logger.info("HIS connection disconnected by admin")
    return _his_connection_payload(False, None, None)


@router.get("/admin/his/visits")
async def admin_his_visits(
    _admin_user: dict = Depends(require_roles("super_admin", "nurse", "viewer")),
):
    data = await _his_proxy_get("/api/visits")
    if data is None:
        return {"available": False, "visits": []}
    return {"available": True, **data}


@router.get("/admin/his/visits/{visit_id}")
async def admin_his_visit_detail(
    visit_id: str,
    _admin_user: dict = Depends(require_roles("super_admin", "nurse", "viewer")),
):
    data = await _his_proxy_get(f"/api/visits/{visit_id}")
    if data is None:
        return {"available": False, "visit": None}
    return {"available": True, "visit": data}


@router.get("/admin/his/patients")
async def admin_his_patients(
    _admin_user: dict = Depends(require_roles("super_admin", "nurse", "viewer")),
):
    """HN master records from the connected hospital DB — the admin
    Database tab's patient (HN) view. Each row already carries the full
    history + last-vitals payload, so no per-patient detail proxy is needed."""
    data = await _his_proxy_get("/api/patients")
    if data is None:
        return {"available": False, "patients": []}
    return {"available": True, **data}

