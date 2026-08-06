"""Generate the Postman collections + environments (postman/ at repo root).

Two collections, both straight from the OpenAPI dumps — nothing hand-written:
  - ai-opd-prescreening-api  : our whole API, folders by URL prefix
  - his-integration          : ONLY the calls we make TO the hospital HIS
                               (adapter calls + the real iMed contract)

Built as Collection Format v2.1 (which is what maps cleanly from OpenAPI),
then converted to **v3 YAML** with `postman collection migrate` — Postman's
Local Mode dropped JSON support, so v3 is what the desktop app reads. The
CLI does the conversion rather than us hand-writing YAML, so the format is
always whatever Postman actually expects.

Ids are uuid5-derived so regenerating does not churn git. Auth is
collection-level bearer; public routes opt out with "noauth", so Postman's
Auth tab shows the truth per request.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from gen_api_doc import auth_map, example_from_schema

from app.services.screening.his.sbar import build_sbar

SCRATCH = Path(__file__).parent
ROOT = Path(__file__).resolve().parents[3]
# Postman's local-workspace layout: the workspace root (our repo root) holds a
# `postman/` folder, and everything inside it is auto-registered in Local View
# (see .postman/resources.yaml, which Postman writes itself). Loose files at
# the folder root are ignored — hence the collections/ + environments/ split.
OUT = ROOT / "postman"
COLLECTIONS = OUT / "collections"
ENVIRONMENTS = OUT / "environments"
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


def example_response(name: str, code: int, status: str, payload, request: dict, note: str = "") -> dict:
    """A saved response example — renders in Postman's Examples dropdown under
    the request, so one request can show every outcome instead of us shipping
    a near-identical request per error code."""
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


def _yaml_scalar(value: str) -> str:
    """YAML is a superset of JSON, so a JSON-quoted string is always a valid
    (and correctly escaped) YAML scalar — no quoting rules to get wrong."""
    return json.dumps(value, ensure_ascii=False)


def write_environment_v3(name: str, values: dict[str, str]) -> Path:
    """Environments in Local Mode are `<name>.environment.yaml`.

    Hand-written rather than migrated: `postman collection migrate` only
    handles collections, and the shape is two keys deep.
    """
    lines = [f"name: {_yaml_scalar(name)}", "values:"]
    for key, value in values.items():
        lines.append(f"  - key: {_yaml_scalar(key)}")
        lines.append(f"    value: {_yaml_scalar(value)}")
    dest = ENVIRONMENTS / f"{name}.environment.yaml"
    dest.write_text("\n".join(lines) + "\n")
    return dest


def write_collection_v3(name: str, payload: dict) -> Path:
    """Write a v2.1 collection through `postman collection migrate` into the
    v3 directory Local Mode reads.

    The target is replaced wholesale, not merged: a renamed or deleted request
    would otherwise leave its old .request.yaml behind and Postman would keep
    showing it.
    """
    dest = COLLECTIONS / name
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "collection.json"
        src.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        staged = Path(tmp) / "v3"
        result = subprocess.run(
            ["postman", "collection", "migrate", str(src), "-o", str(staged)],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or not staged.exists():
            raise SystemExit(
                "postman collection migrate failed — is the Postman CLI installed?\n"
                f"  {result.stdout.strip()} {result.stderr.strip()}"
            )
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(staged), str(dest))
    return dest


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
COLLECTIONS.mkdir(parents=True, exist_ok=True)
ENVIRONMENTS.mkdir(parents=True, exist_ok=True)
write_collection_v3(
    "AI OPD Prescreening API",
    collection("AI OPD Prescreening API", api_desc, api_items, "token"),
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
write_environment_v3("mfu-triage local", env_values)

# ── 2. HIS integration (what WE call on the hospital) ────────────────────────
# Keep in sync with HttpHisAdapter's methods.
ADAPTER_CALLS = [
    ("get", "/api/visits/{visit_id}",
     "⚠️ **OUR ASSUMPTION — iMed documents no counterpart (change request 6).**\n\n"
     "**WE GET** — visit lookup: validate a visit id and pull patient name, birthdate, vitals, history (`HttpHisAdapter.validate_visit`). "
     "**Blocking for go-live**: without a real equivalent the booth cannot link a patient to a visit, and there is then no `visit_id` to assign."),
    ("get", "/api/departments",
     "⚠️ **OUR ASSUMPTION — iMed documents no counterpart (change request 6).**\n\n"
     "**WE GET** — list of department names for routing (`HttpHisAdapter.get_departments`). "
     "Replaceable by a one-time master-data sheet instead of an API."),
    ("post", "/api/visits/{visit_id}/prescreen",
     "**WE POST** — Stage 1 write-back: AI prescreen result right after the booth session (`HttpHisAdapter.push_referral`)."),
    ("put", "/api/visits/{visit_id}/follow-up",
     "⚠️ **OUR ASSUMPTION — iMed documents no counterpart (change request 6).**\n\n"
     "**WE PUT** — follow-up note captured during the interview (`HttpHisAdapter.push_follow_up`)."),
    ("put", "/api/patients/{hn}/history",
     "⚠️ **OUR ASSUMPTION — iMed documents no counterpart (change request 6).**\n\n"
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

JSON_HDR = [{"key": "Content-Type", "value": "application/json"}]

# The body the Phase-3 adapter will actually emit. Note what is ABSENT:
# no queue_number (iMed's queue rules own it), no base_department_id (iMed
# derives it from the service point), no assign_eid (we route to a department,
# never a named doctor), no assessment_equipment (a clinical judgement our
# system does not make).
# Built by the REAL SBAR builder, not hand-written, from a representative
# chest-pain case — so what the hospital reads here is byte-for-byte what our
# code emits. (A hand-typed sample previously claimed an SpO2 reading we do
# not collect and omitted `documentation`, which we do send.)
_SAMPLE_METADATA = {
    "slip_code": "MCH-A1B2-C3D4",
    "visit": {"visit_id": "VN-2026-0001", "age_years": 58},
    "vitals": {
        "systolic": 158, "diastolic": 94, "pulse_bpm": 96, "temperature": 36.8,
        "weight_kg": 72.5, "height_cm": 165, "source": "device",
    },
    "patient_history": {
        "chronic_conditions": "ความดันโลหิตสูง",
        "allergies": "ไม่มี",
        "is_first_time": False,
    },
    "triage_classification": {
        "level": 3, "label": "Urgent", "response_time": "30 นาที",
        "symptoms_summary": "แน่นหน้าอกมา 2 ชั่วโมง ร้าวไปแขนซ้าย",
        "key_reason": "Chest pain with cardiac risk factors",
        "pain_score": 6,
        "disposition_reasons": [{
            "rule_id": "cp_risk_factors",
            "text_th": "เจ็บหน้าอกร่วมกับปัจจัยเสี่ยงโรคหัวใจ",
            "text_en": "Chest pain with cardiac risk factors",
            "citation": "คู่มือคัดกรอง MFU ข้อ 4.2",
        }],
    },
}
_sbar = build_sbar(_SAMPLE_METADATA, department_th="แผนก OPD MED (อายุรกรรม)")

SEND_BODY = {
    "request_id": "MFU-20260807-A1B2C3",
    "visit_id": "{{imedVisitId}}",
    "assign_spid": "SP_OPD_MED_01",
    # Same filter the adapter applies: empty fields are dropped, not sent as
    # nulls — which is why assessment_equipment is absent below.
    "sbar": {k: v for k, v in _sbar.items() if v},
}


SEND_DESC = """**WE POST** — this is *our intended payload*, not a transcription of your
contract. The contract itself is transcribed verbatim in
`docs/imed-patient-assignment-api.md`.

⚠️ `assign_spid` is a **placeholder** pending your master-data codes.

### Deliberately absent

| Field | Why |
|---|---|
| `queue_number` | you generate it — your queue rules own sequencing, prefixes and daily resets. We display what you return and the nurse hands it to the patient. |
| `base_department_id` | you derive it from the service point; one less code for us to keep in sync |
| `assign_eid` | we route to a *department*, never a named doctor. If any destination requires one, that is a product decision for us — see per-department question 2. |
| `sbar.assessment_equipment` | a clinical judgement our system does not make; left for the nurse |

### Where each value comes from

The body above is **not a mock-up** — it is generated by the same
`build_sbar()` our backend calls, from a representative chest-pain case, so
the wording and formatting are exactly what will arrive. Empty fields are
dropped rather than sent as `null`, which is why `assessment_equipment` does
not appear: our system never fills it (the nurse may, in the confirm dialog).

| iMed field | our source |
|---|---|
| `request_id` | allocated at nurse-confirm and **stored**; reused on retry, new one on a genuine reroute |
| `visit_id` | `session.metadata.visit.visit_id`, captured when the patient enters their VN at the booth |
| `assign_spid` | our department code → `department_map.CODE_TO_SPID` ⚠️ |
| `sbar.situation` | nurse-edited chief complaint, else `metadata.triage_classification.symptoms_summary` |
| `sbar.background` | `metadata.patient_history` as labelled segments — chronic conditions, allergies, past surgeries, family history, smoking/alcohol |
| `sbar.assessment` | booth-measured vitals with provenance (`วัดที่บูธ` = cuff, `ผู้ป่วยแจ้ง` = patient-stated) **+ the triage level**, which has nowhere else to go — see change request 1 |
| `sbar.assessment_problem` | `triage_classification.key_reason` + `disposition_reasons[].text_th` with its manual `citation` |
| `sbar.recommend` | destination department + urgency; a reroute is noted here because iMed has no `rerouted` flag |

SBAR is always sent in **Thai**, regardless of the language the patient used
at the booth.

### Timeout is not failure

Postman cannot express this as a saved example, so stated here: if this call
**times out**, we do not know whether the queue row was created. We record it
as `unknown` — never as failed — and any retry reuses the **same**
`request_id`, so it cannot double-book the patient. This is why change
requests 7 and 8 matter.
"""

send_request = {
    "method": "POST",
    "header": JSON_HDR,
    "url": pm_url("/patient-assignments", "imedBaseUrl"),
    "description": SEND_DESC,
    "body": json_body(SEND_BODY),
}

OK_RESULT = {
    "request_id": "MFU-20260807-A1B2C3",
    "status": "STATUS_SUCCESS",
    "result": {
        "visit_id": "VN-2026-0001",
        "visit_queue_id": "VQ-8F2C1A9D44",
        "assign_spid": "SP_OPD_MED_01",
        "assign_eid": "EMP00001",
        "queue_number": "A014",
        "queue_status": "WAITING",
        "sbar_id": "SBAR-4B7E22",
    },
}


def _err(code: str, th: str) -> dict:
    return {"request_id": "MFU-20260807-A1B2C3", "status": "STATUS_BUSINESS_ERROR",
            "message": code, "message_th": th}


PROPOSED_BODY = dict(SEND_BODY)
PROPOSED_BODY["mfu_prescreen"] = {
    "triage_level": 3,
    "triage_scale": "MOPH-5",
    "triage_label": "Urgent",
    "vitals": {
        "systolic": 158, "diastolic": 94, "pulse_bpm": 96,
        "temperature_c": 36.8, "weight_kg": 72.5, "height_cm": 165,
        "measured_at": "2026-08-07T09:12:00+07:00",
        "source": "cuff",
    },
    "confirmed_by": "OPD Nurse (สมหญิง)",
    "source_ref": {"slip_code": "MCH-A1B2-C3D4", "session_ref": "{{session_id}}"},
    "rerouted": False,
}

imed_items = [
    {
        "name": "POST /patient-assignments",
        "request": send_request,
        "response": [
            example_response("200 — STATUS_SUCCESS", 200, "OK", OK_RESULT, send_request,
                             "Nurse sees: the queue number, and gives it to the patient."),
            example_response("409 — VISIT_QUEUE_ALREADY_EXIST", 409, "Conflict",
                             _err("VISIT_QUEUE_ALREADY_EXIST", "ผู้ป่วยอยู่ในคิวของจุดบริการปลายทางแล้ว"),
                             send_request,
                             "We treat this as SUCCESS (our earlier attempt landed). But with no `result` "
                             "we never learn queue_number, so the nurse has nothing to hand over "
                             "-> change request 7."),
            example_response("403 — VISIT_LOCKED_OR_FINANCIAL_DISCHARGED", 403, "Forbidden",
                             _err("VISIT_LOCKED_OR_FINANCIAL_DISCHARGED", "visit ถูกล็อกหรือจำหน่ายทางการเงินแล้ว"),
                             send_request,
                             "Permanent — we do NOT retry. Nurse sees: visit is closed, send the "
                             "patient to the front desk."),
            example_response("422 — SERVICE_POINT_NOT_AVAILABLE", 422, "Unprocessable Entity",
                             _err("SERVICE_POINT_NOT_AVAILABLE", "จุดบริการปลายทางไม่พร้อมให้บริการ"),
                             send_request,
                             "Recoverable. We reopen the department choice so the nurse can reroute "
                             "immediately."),
            example_response("400 — invalid_request", 400, "Bad Request",
                             _err("invalid_request", "ข้อมูลไม่ครบหรือไม่ถูกต้อง"),
                             send_request,
                             "Our bug, not a nurse problem. Logged and alerted; nurse sees "
                             "'system error, contact IT'."),
        ],
    },
    {
        "name": "POST /patient-assignments (+ mfu_prescreen)",
        "request": {
            "method": "POST",
            "header": JSON_HDR,
            "url": pm_url("/patient-assignments", "imedBaseUrl"),
            "description": """**Nothing here is in your contract yet — this is the ask.**

Identical to request 1, plus a single additive `mfu_prescreen` object.

One namespaced wrapper rather than loose top-level fields, for two reasons:
nothing here can collide with a field you add later, and there is no chance of
reading it as something we already send. **We are not asking you to adopt this
shape** — only to tell us where these values should live. If you would rather
have them flat, or under different names, say so; the values are the ask, not
the spelling.

| In `mfu_prescreen` | Change request | Why it matters |
|---|---|---|
| `triage_level`, `triage_scale`, `triage_label` | **CR 1 — highest value** | The 5-level triage is our system's whole output. With no field it is buried in SBAR prose, so your destination queue sorts by arrival time instead of by how sick the patient is. `triage_level` is the integer 1–5 our engine already produces; `triage_scale` is `MOPH-5`, the Thai MOPH ED Triage 5-level guideline (กรมการแพทย์ 2561) our criteria are built on — see `docs/criteria-standards.md`. Name them whatever suits your schema; the value is what matters. |
| `vitals` (structured, with `measured_at` and `source`) | CR 2 | We measure with a real cuff at the booth and know whether a value was instrument-measured or patient-stated. Today all of it flattens into one sentence. |
| `confirmed_by` | CR 3 | Sender identity comes from the token, so iMed records "the MFU triage system", not the nurse who signed off. Matters for audit after an incident. |
| `source_ref` | CR 4 | Lets your staff open the full transcript and the AI's cited reasoning, not just the summary. **`slip_code` and `session_ref` are the same identity, not two keys** — the slip code is the first and last four characters of the session id (`…1ba646bb…811eb` → `MCH-1BA6-11EB`). Store `session_ref` if you store one: the derivation is one-way, so a slip code cannot be resolved back. The slip code exists because it is short enough to print on the patient's paper slip and read out. Neither contains patient data. |
| `rerouted` | — | We know when a nurse overrode the AI's department. There is no iMed field, so today it can only go into `sbar.recommend` as prose. |

If any of these are accepted we implement them our side and this request
becomes request 1.

*Against our mock this reuses request 1's `request_id`, so it replays request
1's result rather than queueing the patient twice — that is the idempotency
rule working, not the proposed fields being ignored.*
""",
            "body": json_body(PROPOSED_BODY),
        },
    },
    {
        "name": "GET /patient-assignments/{request_id}",
        "request": {
            "method": "GET",
            "header": [],
            "url": pm_url("/patient-assignments/{imedRequestId}", "imedBaseUrl"),
            "description": """**This endpoint does not exist yet — it is a request.** It covers three
asks at once.

**CR 8 — an idempotency key we cannot query leaves us blind.** If our call
times out we cannot tell whether the assignment landed. Today the only way to
find out is to send it again and interpret the error. A read endpoint turns a
guess into a fact, and enables end-of-day reconciliation against your gateway
logs.

**CR 7 — a duplicate should return the original `result`.** Standard
idempotency behaviour is 200 with the first response replayed. Without it, a
timeout-then-retry leaves the patient queued while the nurse has no queue
number to give them.

**CR 5 — SBAR read-back.** SBAR is currently write-only for us: we get an
`sbar_id` and nothing else. Reading it back lets us show the nurse what was
actually handed over.

*Returns 404 against our mock — deliberately not built, because it is a
request to you, not something we have decided for you.*
""",
        },
        "response": [
            example_response("200 — assignment found (incl. SBAR read-back)", 200, "OK",
                             {**OK_RESULT, "result": {**OK_RESULT["result"], "sbar": SEND_BODY["sbar"]}},
                             {"method": "GET", "header": [],
                              "url": pm_url("/patient-assignments/{imedRequestId}", "imedBaseUrl")},
                             "Resolves the post-timeout unknown, and returns what we handed over."),
        ],
    },
]

his_desc = (
    "What our system sends to the hospital's real **iMed Patient Assignment "
    "API** — the integration surface for the hospital IT team.\n\n"
    "**imed-assignment / from-contract** — the call as your contract defines "
    "it. This is what we will actually send. Start here.\n\n"
    "**imed-assignment / proposed** — fields and an endpoint we are *asking "
    "for*. Nothing here exists in your contract today.\n\n"
    "Your contract is transcribed verbatim in "
    "`docs/imed-patient-assignment-api.md` and left untouched; our analysis "
    "and the numbered change requests are in `docs/imed-integration-plan.md`.\n\n"
    "Auth is a single bearer token (`hisToken`). Every ⚠️ value is a "
    "placeholder awaiting your master data.\n\n"
    "*The calls our adapter makes against our own demo mock HIS live in a "
    "separate collection, `Mock HIS (demo only)` — they are our assumptions, "
    "not your API.*"
)
IMED_FOLDER_DESC = """The hospital's `POST /patient-assignments`, split by
status: what your contract already defines, and what we are asking you to add.

**These are our payloads, not a transcription of your contract** — that is
`docs/imed-patient-assignment-api.md`, left exactly as you issued it.
"""
CONTRACT_FOLDER_DESC = """Contract-compliant. Every field here is one your
contract already defines, so this is what we will send at go-live.

⚠️ `assign_spid` is a placeholder pending your master-data codes.

Open the request's **Examples** dropdown to see how we handle each response,
including all four error codes.
"""
PROPOSED_FOLDER_DESC = """⚠️ **Nothing in this folder exists in your contract.**
These are our numbered change requests, made runnable so you can see exactly
what we mean.

* **PROPOSED additions** — values our system produces that currently have
  nowhere to go, isolated in one additive `mfu_prescreen` object so they
  cannot be mistaken for something we already send (CR 1–4).
* **PROPOSED lookup** — a read endpoint that would resolve the post-timeout
  unknown state and let us read an SBAR back (CR 5, 7, 8).

Anything you accept, we implement our side. Anything you reject, we drop —
these are questions, not requirements.
"""
MOCK_COLLECTION_DESC = """Calls our adapter makes against **our own demo mock
HIS** — this is *not* the hospital's API.

⚠️ **Everything here is our assumption.** Your assignment contract covers one
direction only (sending a patient to a service point), so the reads and the
other write-backs below are shapes we invented to keep the demo working. They
are on the table for discussion, not decisions we have made for you.

The **visit lookup** is the blocking one (change request 6): the booth starts
from a patient entering their VN, and without a real equivalent we cannot
identify them, cannot pull history, and have no `visit_id` to assign later.

Runs against `hisBaseUrl` (the mock on :8001), not the hospital.
"""
write_collection_v3(
    "HIS Integration (hospital-facing)",
    collection("HIS Integration (hospital-facing)", his_desc, [
        {
            "name": "imed-assignment",
            "description": IMED_FOLDER_DESC,
            "item": [
                {
                    "name": "from-contract",
                    "description": CONTRACT_FOLDER_DESC,
                    "item": imed_items[:1],
                },
                {
                    "name": "proposed",
                    "description": PROPOSED_FOLDER_DESC,
                    "item": imed_items[1:],
                },
            ],
        },
    ], "hisToken"),
)
write_collection_v3(
    "Mock HIS (demo only)",
    collection("Mock HIS (demo only)", MOCK_COLLECTION_DESC, [
        {"name": "our-current-calls", "item": current_items},
    ], "hisToken"),
)
write_environment_v3("mfu-his local", {
        "hisBaseUrl": "http://localhost:8001",
        # Points at our mock's future /api/v1 mount so the same collection runs
        # locally; swap for the hospital's UAT host when they issue it.
        "imedBaseUrl": "http://localhost:8001/api/v1",
        "hisToken": "demo-his-key",
        # Seeded sample rows so every request works on import; replace with a
        # real VN/HN when pointing at a hospital environment.
        "visit_id": "990000000000000001",
        "hn": "09900001",
        "imedVisitId": "990000000000000001",
        "imedRequestId": "MFU-20260807-A1B2C3",
        "session_id": "",
    })

print(f"postman: {sum(len(v) for v in folders.values())} requests in {len(folders)} folders"
      f" + {len(current_items) + len(imed_items)} HIS requests -> {OUT}")

# Optional Windows-side mirror: the Postman desktop folder picker can't browse
# WSL paths, so point POSTMAN_MIRROR_DIR at e.g. /mnt/d/postman to keep a copy
# Postman can watch. Unset (the default) = repo files are the only copy.
mirror = os.environ.get("POSTMAN_MIRROR_DIR")
if mirror:
    dest = Path(mirror) / "postman"
    # Replace, don't merge: a renamed collection/request would otherwise leave
    # its old files behind and Postman would keep listing them.
    for sub in ("collections", "environments"):
        if (dest / sub).exists():
            shutil.rmtree(dest / sub)
    shutil.copytree(OUT, dest, dirs_exist_ok=True)
    print(f"mirrored to {dest}")
