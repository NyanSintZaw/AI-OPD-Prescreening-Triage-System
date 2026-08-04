"""Generate markdown API reference from the dumped OpenAPI specs.
Auth roles are scraped from main.py source (require_roles isn't in OpenAPI)."""
import json, re, sys
from pathlib import Path

SCRATCH = Path(__file__).parent
API_SRC = Path(__file__).resolve().parents[2] / "app" / "main.py"

spec = json.load(open(SCRATCH / "openapi.json"))
his_spec = json.load(open(SCRATCH / "openapi_his.json"))


def build_auth_map(src: str) -> dict[tuple[str, str], str]:
    """(method, path) -> roles string, by scanning decorator blocks."""
    auth: dict[tuple[str, str], str] = {}
    blocks = re.split(r"\n(?=@app\.)", src)
    for b in blocks:
        m = re.match(r'@app\.(get|post|put|delete|patch|websocket)\(\s*\n?\s*"([^"]+)"', b)
        if not m:
            continue
        method, path = m.group(1), m.group(2)
        # only look at this endpoint's function body up to the next def-level statement
        r = re.search(r"require_roles\(([^)]*)\)", b)
        if r:
            roles = re.findall(r'"([^"]+)"', r.group(1))
            auth[(method, path)] = ", ".join(roles)
    return auth


auth_map = build_auth_map(API_SRC.read_text())


def deref(spec, ref):
    name = ref.rsplit("/", 1)[-1]
    return name, spec["components"]["schemas"].get(name, {})


def type_str(spec, prop):
    if "$ref" in prop:
        return deref(spec, prop["$ref"])[0]
    if "anyOf" in prop:
        return " or ".join(type_str(spec, p) for p in prop["anyOf"])
    t = prop.get("type", "any")
    if t == "array":
        return f"array of {type_str(spec, prop.get('items', {}))}"
    if "enum" in prop:
        vals = " \\| ".join(f"`{v}`" for v in prop["enum"])
        return f"{t} — one of {vals}"
    if prop.get("format"):
        return f"{t} ({prop['format']})"
    return t


def example_from_schema(spec, schema, depth=0):
    """Build a placeholder example value straight from the schema —
    defaults and enums come from the code, placeholders fill the rest."""
    if depth > 6:
        return None
    if "$ref" in schema:
        return example_from_schema(spec, deref(spec, schema["$ref"])[1], depth + 1)
    if "anyOf" in schema:
        non_null = [s for s in schema["anyOf"] if s.get("type") != "null"]
        return example_from_schema(spec, non_null[0] if non_null else schema["anyOf"][0], depth)
    if "default" in schema and schema["default"] is not None:
        return schema["default"]
    if "enum" in schema:
        return schema["enum"][0]
    t = schema.get("type")
    if t == "string":
        fmt = schema.get("format")
        if fmt == "uuid":
            return "00000000-0000-0000-0000-000000000000"
        if fmt == "date-time":
            return "2026-08-04T09:00:00Z"
        if fmt == "binary":
            return "<file>"
        return "string"
    if t == "integer":
        return 0
    if t == "number":
        return 0.0
    if t == "boolean":
        return False
    if t == "array":
        item = example_from_schema(spec, schema.get("items", {}), depth + 1)
        return [item] if item is not None else []
    if t == "object" or "properties" in schema:
        props = schema.get("properties", {})
        if not props:
            return {}
        return {
            name: example_from_schema(spec, p, depth + 1)
            for name, p in props.items()
        }
    return None


def example_block(spec, schema, label):
    ex = example_from_schema(spec, schema)
    if ex is None:
        return None
    return f"\n{label}\n\n```json\n{json.dumps(ex, indent=2, ensure_ascii=False)}\n```"


def schema_table(spec, schema, indent_names=True):
    """Render a schema's properties as a markdown table body."""
    if "$ref" in schema:
        _, schema = deref(spec, schema["$ref"])
    props = schema.get("properties")
    if not props:
        return None
    required = set(schema.get("required", []))
    rows = []
    for name, p in props.items():
        req = "Y" if name in required else "N"
        desc = (p.get("description") or p.get("title") or "").replace("\n", " ")
        default = p.get("default")
        if default is not None and default != "":
            desc = (desc + f" (default: `{json.dumps(default, ensure_ascii=False)}`)").strip()
        rows.append(f"| `{name}` | {type_str(spec, p)} | {req} | {desc} |")
    return "| Field | Type | Required | Notes |\n|---|---|---|---|\n" + "\n".join(rows)


def render_op(spec, path, method, op, auth_map):
    lines = []
    lines.append(f"### `{method.upper()} {path}`")
    summary = op.get("summary") or ""
    desc = (op.get("description") or "").strip()
    if summary:
        lines.append(f"\n{summary}." if not summary.endswith(".") else f"\n{summary}")
    if desc:
        lines.append(f"\n{desc}")
    roles = auth_map.get((method, path))
    if roles:
        lines.append(f"\n**Auth:** bearer token (roles: {roles})")
    else:
        lines.append("\n**Auth:** none")
    # parameters
    params = op.get("parameters", [])
    qp = [p for p in params if p.get("in") == "query"]
    pp = [p for p in params if p.get("in") == "path"]
    if pp:
        lines.append("\n**Path params:** " + ", ".join(f"`{p['name']}`" for p in pp))
    if qp:
        rows = []
        for p in qp:
            sch = p.get("schema", {})
            req = "Y" if p.get("required") else "N"
            d = sch.get("default")
            note = f"default: `{json.dumps(d)}`" if d is not None else ""
            rows.append(f"| `{p['name']}` | {type_str(spec, sch)} | {req} | {note} |")
        lines.append("\n**Query params:**\n\n| Param | Type | Required | Notes |\n|---|---|---|---|\n" + "\n".join(rows))
    # request body
    body = op.get("requestBody")
    if body:
        content = body.get("content", {})
        for ctype, media in content.items():
            sch = media.get("schema", {})
            name = sch.get("$ref", "").rsplit("/", 1)[-1] if "$ref" in sch else None
            table = schema_table(spec, sch)
            hdr = f"\n**Request body** (`{ctype}`" + (f", `{name}`" if name else "") + "):"
            if table:
                lines.append(hdr + "\n\n" + table)
            else:
                lines.append(hdr + " see schema in /docs")
            if ctype == "application/json":
                ex = example_block(spec, sch, "Example request:")
                if ex:
                    lines.append(ex)
    # responses
    for code, resp in op.get("responses", {}).items():
        if code == "422":
            continue
        content = resp.get("content", {})
        sch = content.get("application/json", {}).get("schema", {}) if content else {}
        name = None
        if "$ref" in sch:
            name = sch["$ref"].rsplit("/", 1)[-1]
        elif sch.get("type") == "array" and "$ref" in sch.get("items", {}):
            name = "array of " + sch["items"]["$ref"].rsplit("/", 1)[-1]
        rdesc = resp.get("description", "")
        if name:
            lines.append(f"\n**Response {code}:** `{name}`")
            ex = example_block(spec, sch, "Example response:")
            if ex:
                lines.append(ex)
        elif content:
            lines.append(f"\n**Response {code}:** JSON ({rdesc})")
        else:
            lines.append(f"\n**Response {code}:** {rdesc or 'empty'}")
    return "\n".join(lines)


def render_spec(spec, auth_map, heading_level="##"):
    out = []
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            out.append(render_op(spec, path, method, op, auth_map))
    return "\n\n---\n\n".join(out)


# response-model appendix: every referenced schema, once
def render_schemas(spec, skip_prefixes=("HTTPValidationError", "ValidationError", "Body_")):
    out = []
    for name, schema in sorted(spec.get("components", {}).get("schemas", {}).items()):
        if any(name.startswith(p) for p in skip_prefixes):
            continue
        table = schema_table(spec, schema)
        title = schema.get("description", "").strip().replace("\n", " ")
        block = f"### `{name}`" + (f"\n\n{title}" if title else "")
        if table:
            block += "\n\n" + table
        out.append(block)
    return "\n\n".join(out)


main_body = render_spec(spec, auth_map)
his_body = render_spec(his_spec, {})
schemas_md = render_schemas(spec)
his_schemas_md = render_schemas(his_spec)

Path(SCRATCH / "generated_main.md").write_text(main_body)
Path(SCRATCH / "generated_his.md").write_text(his_body)
Path(SCRATCH / "generated_schemas.md").write_text(schemas_md)
Path(SCRATCH / "generated_his_schemas.md").write_text(his_schemas_md)
print("ops:", main_body.count("### `"), "| his ops:", his_body.count("### `"),
      "| schemas:", schemas_md.count("### `"), "| his schemas:", his_schemas_md.count("### `"))
