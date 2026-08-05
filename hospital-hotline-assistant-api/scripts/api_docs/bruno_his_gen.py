"""Generate bruno-his-integration/ — the hospital-facing collection.

Contains ONLY the calls OUR system makes to the hospital HIS:
  - the 6 endpoints HttpHisAdapter uses today (bodies from the mock-HIS
    OpenAPI spec, which defines our current integration contract), and
  - the real iMed POST /patient-assignments (bodies verbatim from the
    hospital's own API contract PDF, see docs/imed-patient-assignment-api.md).
"""
import json
from pathlib import Path

from gen_api_doc import example_from_schema

SCRATCH = Path(__file__).parent
ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "bruno-his-integration"

his_spec = json.load(open(SCRATCH / "openapi_his.json"))

# (method, path, our purpose) — keep in sync with HttpHisAdapter methods
ADAPTER_CALLS = [
    ("get", "/api/visits/{visit_id}",
     "WE GET — visit lookup: validate a visit id and pull patient name, birthdate, vitals, history (HttpHisAdapter.validate_visit)."),
    ("get", "/api/departments",
     "WE GET — list of department names for routing (HttpHisAdapter.get_departments)."),
    ("post", "/api/visits/{visit_id}/prescreen",
     "WE POST — Stage 1 write-back: AI prescreen result right after the booth session (HttpHisAdapter.push_referral)."),
    ("put", "/api/visits/{visit_id}/routing",
     "WE PUT — Stage 2 write-back: nurse-confirmed department routing (HttpHisAdapter.confirm_routing). Real-iMed counterpart: POST /patient-assignments."),
    ("put", "/api/visits/{visit_id}/follow-up",
     "WE PUT — follow-up note captured during the interview (HttpHisAdapter.push_follow_up)."),
    ("put", "/api/patients/{hn}/history",
     "WE PUT — patient history (allergies, chronic conditions, ...) updated at the booth (HttpHisAdapter.push_patient_history)."),
]

AUTH_HEADERS = [
    "headers {",
    "  Authorization: Bearer {{hisToken}}",
    "  X-API-Key: {{hisToken}}",
    "}",
    "",
]


def write_bru(dir_: Path, name: str, seq: int, method: str, url: str,
              body_json, docs: str) -> None:
    lines = [
        "meta {",
        f"  name: {name}",
        "  type: http",
        f"  seq: {seq}",
        "}",
        "",
        f"{method} {{",
        f"  url: {url}",
        f"  body: {'json' if body_json is not None else 'none'}",
        "  auth: none",
        "}",
        "",
        *AUTH_HEADERS,
    ]
    if body_json is not None:
        body = json.dumps(body_json, indent=2, ensure_ascii=False)
        lines += ["body:json {", *("  " + ln for ln in body.splitlines()), "}", ""]
    lines += ["docs {", *("  " + ln for ln in docs.splitlines()), "}", ""]
    dir_.mkdir(parents=True, exist_ok=True)
    slug = name.lower().replace(" ", "-").replace("/", "-").replace("{", "").replace("}", "")
    (dir_ / f"{slug}.bru").write_text("\n".join(lines))


# ── 1. calls we make today (mock-HIS contract) ────────────────────────────────
d = OUT / "current-contract"
for seq, (method, path, purpose) in enumerate(ADAPTER_CALLS, 1):
    op = his_spec["paths"][path][method]
    rb = op.get("requestBody", {}).get("content", {}).get("application/json", {})
    body = example_from_schema(his_spec, rb["schema"]) if rb else None
    desc = (op.get("description") or op.get("summary") or "").strip()
    docs = purpose + ("\n\n" + desc if desc else "")
    url = "{{hisBaseUrl}}" + path.replace("{", "{{").replace("}", "}}")
    write_bru(d, f"{method.upper()} {path}", seq, method, url, body, docs)

# ── 2. real iMed contract (bodies verbatim from the hospital's spec) ──────────
d = OUT / "imed-real-contract"
IMED_DOCS = (
    "WE POST — the hospital's real iMed Patient Assignment API "
    "(spec: docs/imed-patient-assignment-api.md, from iMed Core's contract PDF). "
    "Sends a registered visit to a destination service point; replaces the "
    "current-contract routing call when we go live. Idempotent per request_id — "
    "retry a 409 with the SAME request_id. Sender identity and source service "
    "point come from the Bearer token, never from the body."
)
write_bru(d, "POST /patient-assignments (normal)", 1, "post",
          "{{imedBaseUrl}}/patient-assignments",
          {
              "request_id": "THIRD-PARTY-20260724-000001",
              "visit_id": "VISIT_ID_FROM_IMED",
              "assign_spid": "SP_DOCTOR_01",
              "assign_eid": "EMP00001",
              "base_department_id": "DEPT_MED",
              "queue_number": "A001",
          },
          IMED_DOCS)
write_bru(d, "POST /patient-assignments (with SBAR)", 2, "post",
          "{{imedBaseUrl}}/patient-assignments",
          {
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
          },
          IMED_DOCS + "\n\nSBAR variant — iMed uses assignSbarVisit and saves the handover.")

# ── collection root + environment ─────────────────────────────────────────────
(OUT / "bruno.json").write_text(json.dumps({
    "version": "1",
    "name": "his-integration (hospital-facing)",
    "type": "collection",
    "ignore": ["node_modules", ".git"],
}, indent=2) + "\n")

env_dir = OUT / "environments"
env_dir.mkdir(exist_ok=True)
(env_dir / "local.bru").write_text("""vars {
  hisBaseUrl: http://localhost:8001
  imedBaseUrl: https://uat-host/api/v1
  hisToken:
  visit_id:
  hn:
}
""")

print(f"wrote {len(ADAPTER_CALLS) + 2} requests into {OUT}")
