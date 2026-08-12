"""Generate docs/ai-model-io.md and the AI Model Postman collection.

Run through scripts/api_docs/generate.py — never by hand, or the examples
stop matching the code that produces them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from model_io import BILINGUAL_CALLS, WITHHELD, calls, openai_body, openai_response

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC_PATH = REPO_ROOT / "docs" / "ai-model-io.md"

MODEL_NAME = "{{aiModelName}}"

HEADER = """# What we send to the AI model, and what comes back

**Generated — do not edit by hand.** Every prompt below is built by the same
functions the engine runs (`scripts/api_docs/model_io.py`), so this file
cannot drift from what actually goes on the wire.

## The rule

The model reads what the patient said and phrases what the rules decided.
**It is never given anything that identifies the patient.** The session
holds all of this and sends none of it:

| Held in the session | Sent to the model |
|---|---|
{withheld_rows}

This is enforced by `tests/screening/test_no_pii_in_prompts.py`, which
rebuilds every prompt with a state full of identifiers and fails if one
appears. Two used to: the explanation prompt carried the patient's name so
the reply could greet them, and the identity gate asked *"You are <name>, is
that correct?"*. The greeting now uses a `[NAME]` placeholder substituted
after the reply comes back; the gate never needed the name at all.

### The one thing we cannot filter

The patient's own words are sent verbatim — they have to be, it is what the
extraction reads. A patient may say their own name, their HN, or anything
else out loud, and no filter catches that reliably in free Thai speech.

**That is the reason the model is hosted in the hospital.** With inference on
a workstation on the ward network, an utterance that happens to contain an
identifier never leaves the building, and there is no third party holding a
transcript. Redacting what we control is worth doing; it is not what makes
this safe.

## Where the model sits

```
kiosk ──audio──> booth backend ──HTTP──> model server (hospital workstation)
                      │                  OpenAI-compatible /v1/chat/completions
                      │                  vLLM or Ollama, weights on local disk
                      ├── rules engine   ← decides the triage level + department
                      └── Postgres       ← state, audit
```

The model is reached through `model_adapter.py`, which is a config switch,
not a code path: `SCREENING_MODEL_PROVIDER=openai_compatible` plus
`SCREENING_OPENAI_BASE_URL=http://<workstation>:8000/v1`. Nothing in the
engine knows which backend answered.

**Requests carry no session id, no auth identity, and no cookies** — each
call is a standalone completion. The server needs no state between turns and
keeps nothing that could be joined back to a patient.

## What is audited

`ai_inference_audit` records the call site, model name, prompt version,
latency, whether it succeeded, the rules trace and any validator violations.
**It does not store prompts or completions** — so the audit trail can be read
by staff without exposing what a patient said.

## The calls

One turn makes one extraction call, then either a paraphrase or an
explanation. Gates fire only when the deterministic classifier is unsure.
Every call is bounded by `ainvoke_with_timeout`; a timeout falls back to
deterministic behaviour rather than blocking the booth.

"""


def _fence(value: Any, lang: str = "json") -> str:
    body = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    return f"```{lang}\n{body}\n```"


def build_markdown() -> str:
    rows = "\n".join(
        f"| `{key}` = `{value}` | never |" for key, value in WITHHELD.items()
    )
    parts = [HEADER.format(withheld_rows=rows)]

    english = {c["id"]: c for c in calls("en")}
    for call in calls("th"):
        parts.append(f"### {call['title']}\n")
        parts.append(f"**When:** {call['when']}\n")
        if call["id"] in BILINGUAL_CALLS:
            parts.append(
                "**Prompt language: bilingual.** The booth sends the Thai "
                "prompt to a Thai session and the English one to an English "
                "session — the model is instructed in the language it must "
                "reply in, because this reply reaches the patient.\n"
            )
            parts.append("**Prompt sent (Thai session):**\n")
            parts.append(_fence(call["prompt"], "text"))
            parts.append("\n**Prompt sent (English session):**\n")
            parts.append(_fence(english[call["id"]]["prompt"], "text"))
        else:
            parts.append(
                "**Prompt language: English**, whatever the patient speaks — "
                "this call produces structured data, not patient-facing text, "
                "so the instructions do not need translating. The patient's "
                "own words pass through verbatim in whatever language they "
                "spoke, and the finding catalog carries both languages.\n"
            )
            parts.append("**Prompt sent:**\n")
            parts.append(_fence(call["prompt"], "text"))
        if call["structured"]:
            parts.append(
                "\n**Reply is schema-constrained** — the server is given this "
                "JSON Schema, so a local model cannot answer with prose:\n"
            )
            parts.append(_fence(call["schema"]))
        parts.append("\n**Reply we act on:**\n")
        parts.append(_fence(call["response"], "json" if call["structured"] else "text"))
        if call.get("post"):
            parts.append(f"\n{call['post']}\n")
        parts.append("")

    parts.append("## Running it against a workstation\n")
    parts.append(
        "The `AI Model (local inference)` Postman collection carries every "
        "call above as a real `POST /v1/chat/completions`. Point "
        "`aiModelBaseUrl` at the workstation and they run as-is — the same "
        "bytes the booth sends.\n"
    )
    return "\n".join(parts)


def build_postman_items() -> list[dict[str, Any]]:
    """Postman v2.1 items; the generator converts the collection to v3."""
    from postman_gen import JSON_HDR, example_response, pm_url

    items = []
    # Thai is the booth's default; the English variants of the two
    # patient-facing prompts ship alongside so the hospital can run both.
    both = list(calls("th")) + [
        {**c, "id": f"{c['id']} (en)"} for c in calls("en") if c["id"] in BILINGUAL_CALLS
    ]
    for call in both:
        body = openai_body(call, MODEL_NAME)
        request = {
            "method": "POST",
            "header": JSON_HDR,
            "url": pm_url("/chat/completions", "aiModelBaseUrl"),
            "body": {
                "mode": "raw",
                "raw": json.dumps(body, ensure_ascii=False, indent=2),
                "options": {"raw": {"language": "json"}},
            },
            "description": (
                f"**{call['title']}**\n\n{call['when']}\n\n"
                "Carries no patient identifier — see `docs/ai-model-io.md`."
            ),
        }
        items.append({
            "name": call["id"],
            "request": request,
            "response": [
                example_response(
                    "200 — what the engine parses",
                    200,
                    "OK",
                    openai_response(call, MODEL_NAME),
                    request,
                    None,
                )
            ],
        })
    return items
