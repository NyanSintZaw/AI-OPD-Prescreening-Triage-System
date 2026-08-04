"""Generate a Bruno collection (bruno/ at repo root) from the OpenAPI dump.
Reuses gen_api_doc's auth map + example builder so bodies match the docs."""
import json
import re
from pathlib import Path

from gen_api_doc import auth_map, example_from_schema

SCRATCH = Path(__file__).parent
ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "bruno"

spec = json.load(open(SCRATCH / "openapi.json"))

# folder per first meaningful path segment
def folder_for(path: str) -> str:
    seg = [s for s in path.split("/") if s and not s.startswith("{")]
    if not seg:
        return "misc"
    if seg[0] == "admin":
        return "admin-" + (seg[1] if len(seg) > 1 else "misc")
    return seg[0]


def slug(method: str, path: str) -> str:
    s = re.sub(r"[{}]", "", path.strip("/")).replace("/", "-") or "root"
    return f"{method}-{s}"


# {param} -> {{param}} env-style placeholders Bruno resolves from vars
def bruno_url(path: str) -> str:
    return "{{baseUrl}}" + re.sub(r"\{(\w+)\}", r"{{\1}}", path)


path_vars: set[str] = set()
counters: dict[str, int] = {}
written = 0

for path, methods in spec["paths"].items():
    for method, op in methods.items():
        folder = folder_for(path)
        d = OUT / folder
        d.mkdir(parents=True, exist_ok=True)
        counters[folder] = counters.get(folder, 0) + 1
        seq = counters[folder]

        path_vars.update(re.findall(r"\{(\w+)\}", path))
        roles = auth_map.get((method, path))

        body_kind = "none"
        body_json = None
        multipart = False
        rb = op.get("requestBody", {}).get("content", {})
        if "application/json" in rb:
            body_kind = "json"
            body_json = example_from_schema(spec, rb["application/json"].get("schema", {}))
        elif "multipart/form-data" in rb:
            body_kind = "multipartForm"
            multipart = True

        # query params with defaults, appended so the request works as-is
        qp = [p for p in op.get("parameters", []) if p.get("in") == "query"]
        query = ""
        if qp:
            parts = []
            for p in qp:
                default = p.get("schema", {}).get("default")
                parts.append(f"{p['name']}={default if default is not None else ''}")
            query = "?" + "&".join(parts)

        name = f"{method.upper()} {path}"
        lines = [
            "meta {",
            f"  name: {name}",
            "  type: http",
            f"  seq: {seq}",
            "}",
            "",
            f"{method} {{",
            f"  url: {bruno_url(path)}{query}",
            f"  body: {body_kind}",
            "  auth: none",
            "}",
            "",
        ]
        if roles:
            lines += [
                "headers {",
                "  Authorization: Bearer {{token}}",
                "}",
                "",
            ]
        if body_json is not None:
            body_str = json.dumps(body_json, indent=2, ensure_ascii=False)
            body_str = "\n".join("  " + line for line in body_str.splitlines())
            lines += ["body:json {", body_str, "}", ""]

        # auto-capture ids/tokens for the testing workflow
        if method == "post" and path == "/admin/login":
            lines += [
                "script:post-response {",
                "  bru.setEnvVar(\"token\", res.body.access_token);",
                "}",
                "",
            ]
        if method == "post" and path == "/sessions":
            lines += [
                "script:post-response {",
                "  bru.setEnvVar(\"session_id\", res.body.id);",
                "}",
                "",
            ]

        docs = (op.get("description") or op.get("summary") or "").strip()
        extra = []
        if roles:
            extra.append(f"Roles: {roles}.")
        if multipart:
            extra.append("Multipart form — pick the file in Bruno's Body tab.")
        if extra:
            docs = (docs + "\n\n" if docs else "") + " ".join(extra)
        if docs:
            lines += ["docs {", *("  " + line for line in docs.splitlines()), "}", ""]

        (d / f"{slug(method, path)}.bru").write_text("\n".join(lines))
        written += 1

# collection root + environment
(OUT / "bruno.json").write_text(json.dumps({
    "version": "1",
    "name": "ai-opd-prescreening-api",
    "type": "collection",
    "ignore": ["node_modules", ".git"],
}, indent=2) + "\n")

env_dir = OUT / "environments"
env_dir.mkdir(exist_ok=True)
env_vars = ["  baseUrl: http://localhost:8000", "  token: ", "  session_id: "]
for v in sorted(path_vars):
    if v != "session_id":
        env_vars.append(f"  {v}: ")
(env_dir / "local.bru").write_text("vars {\n" + "\n".join(env_vars) + "\n}\n")

print(f"wrote {written} requests into {OUT}")
print("folders:", ", ".join(sorted(counters)))
print("path vars:", ", ".join(sorted(path_vars)))
