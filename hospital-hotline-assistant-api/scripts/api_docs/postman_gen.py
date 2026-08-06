"""Generate the Postman collections + environments (postman/ at repo root).

Two collections, both straight from the OpenAPI dumps — nothing hand-written:
  - ai-opd-prescreening-api  : our whole API, folders by URL prefix
  - his-integration          : ONLY the calls we make TO the hospital HIS
                               (adapter calls + the real iMed contract)

Postman Collection Format v2.1. Ids are uuid5-derived so regenerating does
not churn git. Auth is collection-level bearer; public routes opt out with
"noauth", so Postman's Auth tab shows the truth per request.
"""
import json
import os
import re
import shutil
import uuid
from pathlib import Path

from gen_api_doc import auth_map, example_from_schema

SCRATCH = Path(__file__).parent
ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "postman"
SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"

spec = json.load(open(SCRATCH / "openapi.json"))
his_spec = json.load(open(SCRATCH / "openapi_his.json"))


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


def collection(name: str, description: str, items: list, auth_var: str) -> dict:
    return {
        "info": {
            "_postman_id": stable_id(name),
            "name": name,
            "description": description,
            "schema": SCHEMA,
        },
        "auth": {
            "type": "bearer",
            "bearer": [{"key": "token", "value": "{{%s}}" % auth_var, "type": "string"}],
        },
        "item": items,
    }


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


# ── 1. our API ────────────────────────────────────────────────────────────────
def folder_for(path: str) -> str:
    seg = [s for s in path.split("/") if s and not s.startswith("{")]
    if not seg:
        return "misc"
    if seg[0] == "admin":
        # reviews is the nurse portal's workflow — label it so it's findable
        if len(seg) > 1 and seg[1] == "reviews":
            return "admin-reviews (nurse)"
        return "admin-" + (seg[1] if len(seg) > 1 else "misc")
    return seg[0]


folders: dict[str, list] = {}
path_vars: set[str] = set()

for path, methods in spec["paths"].items():
    for method, op in methods.items():
        path_vars.update(re.findall(r"\{(\w+)\}", path))
        roles = auth_map.get((method, path))

        headers = []
        body = None
        rb = op.get("requestBody", {}).get("content", {})
        if "application/json" in rb:
            example = example_from_schema(spec, rb["application/json"]["schema"])
            # Login drives the whole collection — point it at the env vars so
            # the run works on import (schema placeholders would just 401).
            if path == "/admin/login":
                example = {"email": "{{email}}", "password": "{{password}}"}
            body = json_body(example)
            headers.append({"key": "Content-Type", "value": "application/json"})
        elif "multipart/form-data" in rb:
            body = {"mode": "formdata", "formdata": [{"key": "file", "type": "file", "src": []}]}

        query = [
            {
                "key": p["name"],
                "value": str(p.get("schema", {}).get("default", "")),
                "description": "required" if p.get("required") else "",
            }
            for p in op.get("parameters", [])
            if p.get("in") == "query"
        ]

        docs = (op.get("description") or op.get("summary") or "").strip()
        if roles:
            docs = (docs + "\n\n" if docs else "") + f"**Roles:** {roles}"
        else:
            docs = (docs + "\n\n" if docs else "") + "**Auth:** none (patient-facing)."

        request = {
            "method": method.upper(),
            "header": headers,
            "url": pm_url(path, "baseUrl", query),
            "description": docs,
        }
        if body:
            request["body"] = body
        if not roles:
            request["auth"] = {"type": "noauth"}

        item = {"name": f"{method.upper()} {path}", "request": request}
        if method == "post" and path == "/admin/login":
            item["event"] = [capture_script("token", "access_token")]
        elif method == "post" and path == "/sessions":
            item["event"] = [capture_script("session_id", "id")]

        folders.setdefault(folder_for(path), []).append(item)

# admin-login first so `postman collection run` has a token before it reaches
# the protected folders; the rest alphabetical.
api_items = [
    {"name": name, "item": folders[name]}
    for name in sorted(folders, key=lambda n: (n != "admin-login", n))
]
api_desc = (
    "AI OPD Prescreening & Triage System — generated from the FastAPI app's own "
    "OpenAPI definition (`scripts/api_docs/generate.py`), so it never drifts from "
    "the code.\n\n"
    "**Getting started:** select the `local` environment, then run "
    "`POST /admin/login` — the token is captured automatically and every "
    "role-protected request inherits it.\n\n"
    "Seeded logins: `opd.nurse@mfu.local` / `nurse1234` (role `nurse`), "
    "`ops.admin@mfu.local` / `admin1234` (role `super_admin`).\n\n"
    "Not included: `WS /ws/voice/{session_id}` — create it as a Postman "
    "WebSocket request (see `docs/api-reference.md` for the frame contract)."
)
(OUT).mkdir(exist_ok=True)
(OUT / "ai-opd-prescreening-api.postman_collection.json").write_text(
    json.dumps(collection("AI OPD Prescreening API", api_desc, api_items, "token"), indent=2, ensure_ascii=False) + "\n"
)

env_values = {
    "baseUrl": "http://localhost:8000",
    # Local dev seed accounts (migrations 002/003). Swap for the super_admin
    # pair — ops.admin@mfu.local / admin1234 — to exercise admin-only routes.
    "email": "opd.nurse@mfu.local",
    "password": "nurse1234",
    "token": "",
    "session_id": "",
}
env_values.update({v: "" for v in sorted(path_vars) if v != "session_id"})
(OUT / "local.postman_environment.json").write_text(
    json.dumps(environment("mfu-triage local", env_values), indent=2) + "\n"
)

# ── 2. HIS integration (what WE call on the hospital) ────────────────────────
# Keep in sync with HttpHisAdapter's methods.
ADAPTER_CALLS = [
    ("get", "/api/visits/{visit_id}",
     "**WE GET** — visit lookup: validate a visit id and pull patient name, birthdate, vitals, history (`HttpHisAdapter.validate_visit`)."),
    ("get", "/api/departments",
     "**WE GET** — list of department names for routing (`HttpHisAdapter.get_departments`)."),
    ("post", "/api/visits/{visit_id}/prescreen",
     "**WE POST** — Stage 1 write-back: AI prescreen result right after the booth session (`HttpHisAdapter.push_referral`)."),
    ("put", "/api/visits/{visit_id}/routing",
     "**WE PUT** — Stage 2 write-back: nurse-confirmed department routing (`HttpHisAdapter.confirm_routing`). Real-iMed counterpart: `POST /patient-assignments`."),
    ("put", "/api/visits/{visit_id}/follow-up",
     "**WE PUT** — follow-up note captured during the interview (`HttpHisAdapter.push_follow_up`)."),
    ("put", "/api/patients/{hn}/history",
     "**WE PUT** — patient history (allergies, chronic conditions, …) updated at the booth (`HttpHisAdapter.push_patient_history`)."),
]

XKEY = {"key": "X-API-Key", "value": "{{hisToken}}"}
current_items = []
for method, path, purpose in ADAPTER_CALLS:
    op = his_spec["paths"][path][method]
    rb = op.get("requestBody", {}).get("content", {}).get("application/json")
    headers = [XKEY]
    request = {
        "method": method.upper(),
        "header": headers,
        "url": pm_url(path, "hisBaseUrl"),
        "description": purpose + "\n\n" + (op.get("description") or op.get("summary") or "").strip(),
    }
    if rb:
        headers.append({"key": "Content-Type", "value": "application/json"})
        request["body"] = json_body(example_from_schema(his_spec, rb["schema"]))
    current_items.append({"name": f"{method.upper()} {path}", "request": request})

IMED_DESC = (
    "**WE POST** — the hospital's real iMed Patient Assignment API "
    "(spec: `docs/imed-patient-assignment-api.md`, from iMed Core's contract PDF).\n\n"
    "Sends a registered visit to a destination service point; replaces the "
    "current-contract routing call at go-live. Idempotent per `request_id` — "
    "retry a 409 with the SAME `request_id`. Sender identity and source service "
    "point come from the Bearer token, never from the body."
)
imed_items = [
    {
        "name": "POST /patient-assignments (normal)",
        "request": {
            "method": "POST",
            "header": [{"key": "Content-Type", "value": "application/json"}],
            "url": pm_url("/patient-assignments", "imedBaseUrl"),
            "description": IMED_DESC,
            "body": json_body({
                "request_id": "THIRD-PARTY-20260724-000001",
                "visit_id": "VISIT_ID_FROM_IMED",
                "assign_spid": "SP_DOCTOR_01",
                "assign_eid": "EMP00001",
                "base_department_id": "DEPT_MED",
                "queue_number": "A001",
            }),
        },
    },
    {
        "name": "POST /patient-assignments (with SBAR)",
        "request": {
            "method": "POST",
            "header": [{"key": "Content-Type", "value": "application/json"}],
            "url": pm_url("/patient-assignments", "imedBaseUrl"),
            "description": IMED_DESC + "\n\nSBAR variant — iMed uses `assignSbarVisit` and saves the handover.",
            "body": json_body({
                "request_id": "THIRD-PARTY-20260724-000002",
                "visit_id": "VISIT_ID_FROM_IMED",
                "assign_spid": "SP_ER_01",
                "base_department_id": "DEPT_ER",
                "sbar": {
                    "situation": "ผู้ป่วยมีอาการเจ็บหน้าอก",
                    "background": "มีโรคความดันโลหิตสูง",
                    "assessment": "รู้สึกตัวดี vital signs คงที่",
                    "assessment_problem": "สงสัยภาวะกล้ามเนื้อหัวใจขาดเลือด",
                    "assessment_equipment": "ECG monitor",
                    "recommend": "ประเมินโดยแพทย์โดยเร็ว",
                    "documentation": "แนบผล ECG",
                },
            }),
        },
    },
]

his_desc = (
    "Only the calls **our system makes to the hospital HIS** — the integration "
    "surface for the hospital IT team.\n\n"
    "**current-contract**: what `HttpHisAdapter` calls today (bodies from the "
    "mock-HIS OpenAPI spec, which is our present integration contract).\n\n"
    "**imed-real-contract**: the hospital's own iMed API, bodies verbatim from "
    "their contract PDF.\n\n"
    "Both auth schemes are sent (`Authorization: Bearer` for iMed, `X-API-Key` "
    "for the mock) from the single `hisToken` variable — matching "
    "`his_auth_headers()` in the backend."
)
(OUT / "his-integration.postman_collection.json").write_text(
    json.dumps(collection("HIS Integration (hospital-facing)", his_desc, [
        {"name": "current-contract", "item": current_items},
        {"name": "imed-real-contract", "item": imed_items},
    ], "hisToken"), indent=2, ensure_ascii=False) + "\n"
)
(OUT / "his-local.postman_environment.json").write_text(
    json.dumps(environment("mfu-his local", {
        "hisBaseUrl": "http://localhost:8001",
        "imedBaseUrl": "https://uat-host/api/v1",
        "hisToken": "",
        "visit_id": "",
        "hn": "",
    }), indent=2) + "\n"
)

print(f"postman: {sum(len(v) for v in folders.values())} requests in {len(folders)} folders"
      f" + {len(current_items) + len(imed_items)} HIS requests -> {OUT}")

# Optional Windows-side mirror: the Postman desktop folder picker can't browse
# WSL paths, so point POSTMAN_MIRROR_DIR at e.g. /mnt/d/postman to keep a copy
# Postman can watch. Unset (the default) = repo files are the only copy.
mirror = os.environ.get("POSTMAN_MIRROR_DIR")
if mirror:
    dest = Path(mirror)
    dest.mkdir(parents=True, exist_ok=True)
    for f in sorted(OUT.glob("*.json")) + [OUT / "README.md"]:
        shutil.copy2(f, dest / f.name)
    print(f"mirrored to {dest}")
