"""On-prem LLM gateway: makes Ollama reachable, without exposing Ollama.

Ollama binds 127.0.0.1 and cannot be reached from another machine. Changing
that (OLLAMA_HOST=0.0.0.0) would put an UNAUTHENTICATED LLM endpoint on the
hospital LAN, where anyone could send prompts, read model names, or delete
models. This process binds 0.0.0.0 instead and relays to Ollama over
loopback, so exactly one port leaves the machine and it is one we control.

    POST /v1/chat/completions   the triage engine's path (streaming + not)
    POST /v1/completions        legacy completion
    POST /v1/embeddings         384-dim all-minilm, matches pgvector_embed_dim
    GET  /v1/models             what Ollama is serving
    GET  /api/tags|ps|version   native read-only
    GET  /health                upstream reachability + what is pinned

Mutating routes (/api/pull, /api/delete, /api/push, /api/create, /api/copy)
answer 403 by design — see _BLOCKED.

Run:
    pip install -r requirements.txt
    uvicorn server:app --host 0.0.0.0 --port 8092
"""

import json
import logging
import os
import threading
import time

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
logger = logging.getLogger("local-llm")

try:
    from dotenv import load_dotenv

    _ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if load_dotenv(_ENV, override=False):
        logger.info("loaded config from %s", _ENV)
except ImportError:
    pass

# httpx narrates every upstream call, which drowns the one line per request
# that actually matters. LOG_VERBOSE=1 puts it back.
LOG_VERBOSE = os.environ.get("LOG_VERBOSE", "").strip().lower() in ("1", "true", "yes")
if not LOG_VERBOSE:
    for _n in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(_n).setLevel(logging.WARNING)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
TIMEOUT_S = float(os.environ.get("LLM_TIMEOUT_S", "180"))

# Hold this model in VRAM so the first patient never pays the cold load. A
# cold 8B costs ~11 s warm-disk and has been measured at 75 s cold, against
# the backend's 30 s model timeout — the first turn after a restart simply
# dies. OLLAMA_KEEP_ALIVE is NOT a usable lever: Ollama's service respawns
# with its own environment and ignores it. keep_alive=-1 on an API call does
# work, and reports "Forever".
PIN_MODEL = os.environ.get("LLM_PIN_MODEL", "").strip()
# Re-assert on this interval. Ollama is often shared; another client loading a
# different model can evict ours, and by the time it has actually vanished a
# patient is already waiting on the reload. 0 disables.
PIN_INTERVAL_S = float(os.environ.get("LLM_PIN_INTERVAL_S", "60"))

# No authentication lives here, so CORS is not what keeps anyone out — the
# firewall and the tunnel's visibility are. Narrow it when the origins are
# known.
CORS_ORIGINS = [
    o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()
]

# Publishing these would let any caller on the network replace or destroy the
# triage model. Run them on the host.
_BLOCKED = {"/api/pull", "/api/delete", "/api/push", "/api/create", "/api/copy"}


def _norm(name: str) -> str:
    """Ollama always reports an explicit tag; config usually omits it, and a
    bare name means :latest. Comparing them raw makes every check disagree."""
    name = (name or "").strip()
    return name if ":" in name else f"{name}:latest"


def _resident() -> set[str] | None:
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/ps", timeout=5)
        r.raise_for_status()
        return {_norm(m.get("name", "")) for m in r.json().get("models", [])}
    except Exception:      # noqa: BLE001 — a failed check just means try again
        return None


def _pin(quiet: bool = False) -> None:
    if not PIN_MODEL:
        return
    t0 = time.perf_counter()
    # No prompt: Ollama loads and holds the model without generating.
    r = httpx.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": PIN_MODEL, "keep_alive": -1},
        timeout=600,
    )
    r.raise_for_status()
    if not quiet:
        logger.info("pinned %s in %.1f s", PIN_MODEL, time.perf_counter() - t0)


def _watchdog() -> None:
    while True:
        time.sleep(PIN_INTERVAL_S)
        resident = _resident()
        if resident is not None and _norm(PIN_MODEL) not in resident:
            logger.warning(
                "%s was evicted (resident: %s) — re-pinning",
                PIN_MODEL, ", ".join(sorted(resident)) or "nothing",
            )
        try:
            _pin(quiet=True)
        except Exception:      # noqa: BLE001
            logger.exception("re-pin failed; the next turn may pay a cold load")


app = FastAPI(title="Local LLM Gateway (Ollama relay)")
app.add_middleware(
    CORSMiddleware, allow_origins=CORS_ORIGINS,
    allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    if not PIN_MODEL:
        logger.info("LLM_PIN_MODEL unset — the model loads on first use")
        return

    def warm() -> None:
        try:
            _pin()
        except Exception:      # noqa: BLE001 — a cold model costs a turn, not the booth
            logger.exception("initial pin failed; it will load on first use")

    threading.Thread(target=warm, daemon=True, name="pin").start()
    if PIN_INTERVAL_S > 0:
        threading.Thread(target=_watchdog, daemon=True, name="pin-watchdog").start()


@app.get("/")
def index() -> dict:
    return {
        "service": "local-llm — Ollama relay, so 127.0.0.1:11434 stays private",
        "upstream": OLLAMA_URL,
        "routes": [
            "POST /v1/chat/completions",
            "POST /v1/completions",
            "POST /v1/embeddings",
            "GET  /v1/models",
            "GET  /api/tags, /api/ps, /api/version",
            "GET  /health",
        ],
        "blocked": sorted(_BLOCKED),
    }


@app.get("/health")
def health() -> dict:
    resident = _resident()
    return {
        "status": "ok",
        "upstream": OLLAMA_URL,
        "reachable": resident is not None,
        "resident": sorted(resident) if resident else [],
        "pin_model": PIN_MODEL or None,
        "pinned": bool(PIN_MODEL and resident and _norm(PIN_MODEL) in resident),
    }


async def _relay(request: Request, path: str) -> Response:
    if path in _BLOCKED:
        raise HTTPException(
            403,
            f"{path} is not exposed: it can modify or delete models and this "
            "port is unauthenticated. Run it on the host.",
        )
    body = await request.body()
    started = time.perf_counter()
    streaming = False
    if body:
        try:
            streaming = bool(json.loads(body).get("stream", False))
        except Exception:      # noqa: BLE001 — not our JSON to validate
            pass
    url = f"{OLLAMA_URL}{path}"
    headers = {"Content-Type": request.headers.get("content-type", "application/json")}

    if streaming:
        async def relay_stream():
            ttft = None
            chunks = 0
            try:
                async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
                    async with client.stream(
                        request.method, url, content=body or None, headers=headers,
                    ) as r:
                        async for chunk in r.aiter_raw():
                            if ttft is None:
                                ttft = time.perf_counter() - started
                            chunks += 1
                            yield chunk
            except Exception as exc:
                logger.exception("stream relay failed for %s", path)
                # The client already has a 200 body; an SSE error event is the
                # only way left to tell it something went wrong.
                yield f'data: {{"error":{json.dumps(str(exc))}}}\n\n'.encode()
            finally:
                logger.info(
                    "-> LLM   stream done  (ttft=%s, %d chunks, %.2fs total)",
                    f"{ttft:.2f}s" if ttft is not None else "n/a",
                    chunks, time.perf_counter() - started,
                )
        logger.info("<- LLM   %s  %.0f KB prompt (streaming)", path, len(body) / 1024)
        return StreamingResponse(relay_stream(), media_type="text/event-stream")

    if body:
        logger.info("<- LLM   %s  %.0f KB prompt", path, len(body) / 1024)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            r = await client.request(
                request.method, url, content=body or None, headers=headers,
                params=dict(request.query_params),
            )
    except Exception as exc:
        logger.exception("relay failed for %s", path)
        raise HTTPException(502, f"Ollama upstream error: {exc}") from exc

    if body:
        elapsed = time.perf_counter() - started
        usage = {}
        try:
            usage = r.json().get("usage") or {}
        except Exception:      # noqa: BLE001
            pass
        out = usage.get("completion_tokens")
        logger.info(
            "-> LLM   %s tokens back  (%s prompt, %.2fs = %.1f tok/s)",
            out or "?", usage.get("prompt_tokens", "?"), elapsed,
            (out / elapsed) if out and elapsed else 0.0,
        )
    return Response(
        content=r.content, status_code=r.status_code,
        media_type=r.headers.get("content-type", "application/json"),
    )


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    return await _relay(request, "/v1/chat/completions")


@app.post("/v1/completions")
async def completions(request: Request):
    return await _relay(request, "/v1/completions")


@app.post("/v1/embeddings")
async def embeddings(request: Request):
    return await _relay(request, "/v1/embeddings")


@app.get("/v1/models")
async def models(request: Request):
    return await _relay(request, "/v1/models")


@app.api_route("/api/{path:path}", methods=["GET", "POST"])
async def api_relay(request: Request, path: str):
    """Native Ollama API. Blocked paths answer 403 with the reason rather
    than a 404 that leaves the caller guessing."""
    return await _relay(request, f"/api/{path}")
