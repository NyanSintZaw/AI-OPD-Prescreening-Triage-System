"""Postman collections (v2.1 JSON) — generated, nothing hand-written.

Run through scripts/api_docs/generate.py. Output: repo-root `postman/`,
flat files you import into the Postman desktop app (File → Import):

  AI OPD Prescreening API.postman_collection.json   our backend, from app.openapi()
  HIS Integration (Data Requirements V1).postman_collection.json
        what WE call on the hospital — the mock's /api/v1/* routes, which
        implement the hospital's Data Requirements V1. Fields and routes that
        are OURS, beyond the document, are tagged "MFU extension" in each
        request's description (source: the comments in his_mock/main.py and
        his/adapter.py — this file does not decide that list).
  Mock HIS (demo only).postman_collection.json       the mock's /api/* demo scaffolding
  AI Model (local inference).postman_collection.json every call to the AI workstation
  local.postman_environment.json / hospital.postman_environment.json

The two HIS write-back bodies are built by the real builders
(`his/sbar.py`, `his/http_adapter.pdf_vitals`) so what the hospital reads is
byte-for-byte what our adapter emits.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path

SCRATCH = Path(__file__).parent
ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "postman"
SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"

sys.path.insert(0, str(SCRATCH))
from gen_api_doc import auth_map, example_from_schema  # noqa: E402

from app.services.screening.his.http_adapter import BOOTH_LOCATION, pdf_vitals  # noqa: E402
from app.services.screening.his.sbar import build_mfu_prescreen, build_sbar  # noqa: E402

spec = json.load(open(SCRATCH / "openapi.json"))
his_spec = json.load(open(SCRATCH / "openapi_his.json"))

JSON_HDR = [{"key": "Content-Type", "value": "application/json"}]


# ── helpers ──────────────────────────────────────────────────────────────────
def stable_id(name: str) -> str:
    """Deterministic id — same input, same uuid, so git sees no diff."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"mfu-triage/{name}"))


def pm_url(path: str, base_var: str, query: list[dict] | None = None) -> dict:
    """{param} -> {{param}} so Postman resolves it from the environment."""
    templated = re.sub(r"\{(\w+)\}", r"{{\1}}", path)
    raw = "{{%s}}%s" % (base_var, templated)
    if query:
        raw += "?" + "&".join(f"{q['key']}={q['value']}" for q in query)
    url = {
        "raw": raw,
        "host": ["{{%s}}" % base_var],
        "path": [seg for seg in templated.split("/") if seg],
    }
    if query:
        url["query"] = query
    return url


def json_body(payload) -> dict:
    return {
        "mode": "raw",
        "raw": json.dumps(payload, indent=2, ensure_ascii=False),
        "options": {"raw": {"language": "json"}},
    }


def example_response(name: str, code: int, status: str, payload, request: dict, note: str = "") -> dict:
    """A saved example — shows in Postman's Examples dropdown under the request."""
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    if note:
        body = f"// {note}\n" + body
    return {
        "name": name,
        "originalRequest": request,
        "status": status,
        "code": code,
        "_postman_previewlanguage": "json",
        "header": [{"key": "Content-Type", "value": "application/json"}],
        "cookie": [],
        "body": body,
    }


def capture_script(var: str, field: str) -> dict:
    """Save an id/token from the response into the active environment."""
    return {
        "listen": "test",
        "script": {
            "type": "text/javascript",
            "exec": [
                "pm.test('2xx', () => pm.response.to.be.success);",
                f"const v = pm.response.json().{field};",
                "if (pm.environment.name) {",
                f"  pm.environment.set('{var}', v);",
                "} else {",
                f"  pm.collectionVariables.set('{var}', v);",
                "}",
            ],
        },
    }


def collection(name: str, description: str, items: list, auth_var: str | None) -> dict:
    payload = {
        "info": {
            "_postman_id": stable_id(name),
            "name": name,
            "description": description,
            "schema": SCHEMA,
        },
        "item": items,
    }
    if auth_var:
        payload["auth"] = {
            "type": "bearer",
            "bearer": [{"key": "token", "value": "{{%s}}" % auth_var, "type": "string"}],
        }
    return payload


def environment(name: str, values: dict[str, str]) -> dict:
    return {
        "id": stable_id(f"env/{name}"),
        "name": name,
        "values": [
            {"key": k, "value": v, "type": "default", "enabled": True}
            for k, v in values.items()
        ],
        "_postman_variable_scope": "environment",
    }


def write(name: str, payload: dict, kind: str) -> Path:
    path = OUT / f"{name}.postman_{kind}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def op_doc(op: dict) -> str:
    return (op.get("description") or op.get("summary") or "").strip()


def request_from_op(oa_spec: dict, path: str, method: str, op: dict, base_var: str,
                    headers: list[dict], body_override=None) -> dict:
    rb = op.get("requestBody", {}).get("content", {})
    request = {"method": method.upper(), "header": list(headers),
               "url": pm_url(path, base_var, _query(op)), "description": op_doc(op)}
    if body_override is not None:
        request["header"].append(JSON_HDR[0])
        request["body"] = json_body(body_override)
    elif "application/json" in rb:
        request["header"].append(JSON_HDR[0])
        request["body"] = json_body(example_from_schema(oa_spec, rb["application/json"]["schema"]))
    elif "multipart/form-data" in rb:
        request["body"] = {"mode": "formdata", "formdata": [{"key": "file", "type": "file", "src": []}]}
    return request


def _query(op: dict) -> list[dict]:
    return [
        {"key": p["name"], "value": str(p.get("schema", {}).get("default", "")),
         "description": "required" if p.get("required") else ""}
        for p in op.get("parameters", []) if p.get("in") == "query"
    ]


# ── 1. our API ───────────────────────────────────────────────────────────────
def folder_for(path: str) -> str:
    seg = [s for s in path.split("/") if s and not s.startswith("{")]
    if not seg:
        return "misc"
    if seg[0] == "admin":
        if len(seg) > 1 and seg[1] == "reviews":
            return "admin-reviews (nurse)"
        return "admin-" + (seg[1] if len(seg) > 1 else "misc")
    return seg[0]


WS_DOC = """**WebSocket — not runnable from this item.** In Postman: New → WebSocket, URL
`ws://localhost:8000/ws/voice/{{session_id}}`.

Up: binary frames = 16 kHz mono Int16 PCM from the mic; JSON control frames
`{"type":"mute"}` / `{"type":"unmute"}` / `{"type":"end_of_turn"}` / `{"type":"end_call"}`.

Down: binary frames = 24 kHz LINEAR16 PCM reply audio; JSON frames carry
`transcript` (patient + assistant text), `emergency` banner, `awaiting_measurement`,
`assessment_complete`, errors. Every turn is persisted through the same
pipeline as the REST surface — see `docs/api-reference.md`."""

folders: dict[str, list] = {}
path_vars: set[str] = set()
for path, methods in spec["paths"].items():
    for method, op in methods.items():
        path_vars.update(re.findall(r"\{(\w+)\}", path))
        roles = auth_map.get((method, path))
        override = {"email": "{{email}}", "password": "{{password}}"} if path == "/admin/login" else None
        request = request_from_op(spec, path, method, op, "BASE_URL", [], override)
        request["description"] += ("\n\n" if request["description"] else "") + (
            f"**Roles:** {roles}" if roles else "**Auth:** none (patient-facing)."
        )
        if not roles:
            request["auth"] = {"type": "noauth"}
        item = {"name": f"{method.upper()} {path}", "request": request}
        if method == "post" and path == "/admin/login":
            item["event"] = [capture_script("token", "access_token")]
        elif method == "post" and path == "/sessions":
            item["event"] = [capture_script("session_id", "id")]
        folders.setdefault(folder_for(path), []).append(item)

folders.setdefault("ws", []).append({
    "name": "WS /ws/voice/{session_id}",
    "request": {"method": "GET", "header": [], "url": pm_url("/ws/voice/{session_id}", "BASE_URL"),
                "description": WS_DOC, "auth": {"type": "noauth"}},
})

api_items = [{"name": n, "item": folders[n]} for n in sorted(folders, key=lambda n: (n != "admin-login", n))]
api_desc = (
    "AI OPD Prescreening & Triage System — generated from the FastAPI app's own OpenAPI "
    "definition (`scripts/api_docs/generate.py`), so it never drifts from the code.\n\n"
    "**Getting started:** select the `local` environment, run `POST /admin/login` — the token "
    "is captured and every role-protected request inherits it. `POST /sessions` captures "
    "`session_id`.\n\n"
    "Seeded logins: `opd.nurse@mfu.local` / `nurse1234` (nurse), `ops.admin@mfu.local` / "
    "`admin1234` (super_admin)."
)

# ── 2. HIS Integration — Data Requirements V1, what WE call ──────────────────
# Built by the real builders from one representative chest-pain case.
_SAMPLE_METADATA = {
    "slip_code": "MCH-A1B2-C3D4",
    "patient": {"hn": "{{HN}}", "visit_id": None, "age_years": 58, "gender": "male"},
    "vitals": {
        "systolic": 158, "diastolic": 94, "pulse_bpm": 96, "temperature": 36.8, "spo2": 97,
        "weight_kg": 72.5, "height_cm": 165,
        "sources": {"systolic": "device", "diastolic": "device", "pulse_bpm": "device",
                    "temperature": "device", "spo2": "device", "weight_kg": "patient_input",
                    "height_cm": "patient_input"},
        "measured_at": "2026-08-21T09:12:00+07:00",
    },
    "patient_history": {"chronic_conditions": "ความดันโลหิตสูง", "allergies": "ไม่มี", "is_first_time": False},
    "triage_classification": {
        "level": 3, "label": "Urgent", "response_time": "30 นาที",
        "symptoms_summary": "แน่นหน้าอกมา 2 ชั่วโมง ร้าวไปแขนซ้าย",
        "key_reason": "Chest pain with cardiac risk factors", "pain_score": 6,
        "department_code": "opd_internal_medicine",
        "disposition_reasons": [{"rule_id": "cp_risk_factors",
                                 "text_th": "เจ็บหน้าอกร่วมกับปัจจัยเสี่ยงโรคหัวใจ",
                                 "text_en": "Chest pain with cardiac risk factors",
                                 "citation": "คู่มือคัดกรอง MFU ข้อ 4.2"}],
    },
}
_sbar = build_sbar(_SAMPLE_METADATA, department_th="แผนก OPD MED (อายุรกรรม)")
_mfu = build_mfu_prescreen(_SAMPLE_METADATA, confirmed_by="opd.nurse@mfu.local", rerouted=False,
                           session_id="1f0b8c2e-4a77-4d1e-9d3a-2b6e5c7f81aa")

PRESCREEN_BODY = {  # mirrors HttpHisAdapter.push_prescreen
    "visit_id": None, "hn": "{{HN}}",
    "session_ref": "1f0b8c2e-4a77-4d1e-9d3a-2b6e5c7f81aa", "slip_code": "MCH-A1B2-C3D4",
    "first_location": BOOTH_LOCATION,
    "measured_at": _SAMPLE_METADATA["vitals"]["measured_at"],
    "vitals": pdf_vitals(_SAMPLE_METADATA["vitals"]),
}
ASSIGN_BODY = {  # mirrors HttpHisAdapter.confirm_routing
    "request_id": "MFU-20260821-A1B2C3", "visit_id": None, "hn": "{{HN}}",
    "base_department_id": "DEPT_MED",
    "sbar": {k: v for k, v in _sbar.items() if v},
    "mfu_prescreen": _mfu,
}

# V1 routes we call, in adapter order. (section, extension note) — the note
# text restates the comments in his_mock/main.py / his/adapter.py.
EXT = "**MFU extension (not in Data Requirements V1):** "
V1_CALLS = [
    ("get", "/api/v1/patients/{hn}", "§2.1 patient read — `HttpHisAdapter.validate_patient`.",
     EXT + "`gender` (the document has no gender field) and `current_visit` (the document has "
           "no by-HN visit resolution; we carry its `visit_id` as passthrough, never as identity).", None),
    ("put", "/api/v1/patients/{hn}/history", "CR 13 fill-only history write — `push_patient_history`.", "", None),
    ("put", "/api/v1/patients/{hn}/gender", "Fill-only gender write — `push_patient_gender`.",
     EXT + "the whole route; drops away if the hospital records gender itself.", None),
    ("post", "/api/v1/patient-prescreens", "§2.1/§4.3 Stage 1 — `push_prescreen`, objective data only; "
     "the body below is produced by `pdf_vitals()` (allowlist, `hight_cm` spelling is the document's).",
     EXT + "`visit_id` optional — with only the HN the HIS resolves the active visit.", PRESCREEN_BODY),
    ("post", "/api/v1/patient-assignments", "§2.2/§4.4 Stage 2 — `confirm_routing` after nurse sign-off. "
     "`sbar` and `mfu_prescreen` below are built by `his/sbar.py` from a chest-pain case.",
     EXT + "`visit_id` optional (HN fallback); `mfu_prescreen` block (our screening result, stored "
           "verbatim); idempotent replay of the same `request_id` returns the ORIGINAL result (our CR 7).",
     ASSIGN_BODY),
    ("get", "/api/v1/patient-assignments/{request_id}", "Read-back of an assignment by our request id.", "", None),
    ("get", "/api/v1/visits/{visit_id}", "CR 6 VN lookup — used when a nurse types a VN in the publish dialog.", "", None),
    ("get", "/api/v1/departments", "CR 18 routing destinations — re-check `department_map.CODE_TO_DEPT_ID`.", "", None),
]
his_items = []
for method, path, purpose, ext, body in V1_CALLS:
    op = his_spec["paths"][path][method]
    request = request_from_op(his_spec, path, method, op, "HIS_BASE_URL", [], body)
    request["description"] = "\n\n".join(s for s in (purpose, ext, op_doc(op)) if s)
    his_items.append({"name": f"{method.upper()} {path}", "request": request})
his_desc = (
    "What our backend calls on the hospital HIS — the `/api/v1/*` surface of "
    "`hospital-his-mock`, which implements the hospital's **Data Requirements V1** "
    "(repo-root PDF). Anything beyond the document is tagged **MFU extension** in the "
    "request description. Bodies are generated by the same code the adapter runs.\n\n"
    "Auth: `Authorization: Bearer {{IMED_TOKEN}}` (the mock also accepts `X-API-Key`)."
)

# ── 3. Mock HIS demo scaffolding ─────────────────────────────────────────────
mock_items = []
for path, methods in his_spec["paths"].items():
    if path.startswith("/api/v1/"):
        continue
    for method, op in methods.items():
        request = request_from_op(his_spec, path, method, op, "HIS_BASE_URL",
                                  [{"key": "X-API-Key", "value": "{{HIS_API_KEY}}"}])
        request["auth"] = {"type": "noauth"}
        mock_items.append({"name": f"{method.upper()} {path}", "request": request})
mock_desc = ("Demo-only routes of `hospital-his-mock` (`/api/*`): seeded visits/patients, vitals "
             "push, `POST /api/admin/reset`. Scaffolding for the before/after demo — absent at go-live.")

# ── 4. AI model (local inference) ────────────────────────────────────────────
from model_io_gen import build_postman_items  # noqa: E402

ai_desc = ("Every call our backend makes to the AI workstation, as real requests: four "
           "`/chat/completions` (extraction, question, explain, gates, surveillance) + STT + TTS. "
           "Point `LLM_BASE_URL` at the server and run them — these are the bytes the booth sends. "
           "No request carries a patient identifier; see `docs/ai-model-io.md`.")

# ── write ────────────────────────────────────────────────────────────────────
if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True)
written = [
    write("AI OPD Prescreening API", collection("AI OPD Prescreening API", api_desc, api_items, "token"), "collection"),
    write("HIS Integration (Data Requirements V1)",
          collection("HIS Integration (Data Requirements V1)", his_desc, his_items, "IMED_TOKEN"), "collection"),
    write("Mock HIS (demo only)", collection("Mock HIS (demo only)", mock_desc, mock_items, None), "collection"),
    write("AI Model (local inference)", collection("AI Model (local inference)", ai_desc, build_postman_items(), None), "collection"),
]
local_env = {
    "BASE_URL": "http://localhost:8000", "email": "opd.nurse@mfu.local", "password": "nurse1234",
    "token": "", "session_id": "",
    "HIS_BASE_URL": "http://localhost:8001", "IMED_TOKEN": "demo-his-key", "HIS_API_KEY": "demo-his-key",
    "HN": "09900001",
    "LLM_BASE_URL": "http://localhost:8000/v1", "LLM_MODEL": "Qwen2.5-7B-Instruct",
    "STT_MODEL": "whisper-large-v3", "TTS_MODEL": "tts-1", "TTS_LOCAL_VOICE_TH": "th-female-1",
}
local_env.update({v: "" for v in sorted(path_vars) if v not in local_env})
hospital_env = {k: ("" if k not in ("email", "password", "token", "session_id", "HN") else "") for k in local_env}
hospital_env.update({"BASE_URL": "https://<booth-backend>", "HIS_BASE_URL": "https://<his-host>",
                     "LLM_BASE_URL": "http://<ai-workstation>:8000/v1"})
written += [write("local", environment("local", local_env), "environment"),
            write("hospital", environment("hospital", hospital_env), "environment")]
shutil.copy(SCRATCH / "postman_README.md", OUT / "README.md")
for p in written:
    json.loads(p.read_text(encoding="utf-8"))  # every file must re-parse
    print("wrote", p.relative_to(ROOT))

# Optional mirror for a Postman install that can't see the repo (WSL → Windows).
mirror = os.environ.get("POSTMAN_MIRROR_DIR")
if mirror:
    dest = Path(mirror) / "postman"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(OUT, dest)
    print("mirrored to", dest)
