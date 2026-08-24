"""Generate docs/ai-model-io.md and the AI Model Postman collection.

Run through scripts/api_docs/generate.py — never by hand, or the examples
stop matching the code that produces them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from model_io import BILINGUAL_CALLS, WITHHELD, calls, openai_body, openai_response, speech_calls

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC_PATH = REPO_ROOT / "docs" / "ai-model-io.md"

MODEL_NAME = "{{LLM_MODEL}}"

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

## Where the AI side sits

```
kiosk ──audio──> booth backend ──HTTP──> AI workstation (hospital LAN)
                      │                  /v1/chat/completions   LLM (vLLM / Ollama)
                      │                  /v1/audio/transcriptions  STT (Whisper)
                      │                  /v1/audio/speech          TTS
                      ├── rules engine   ← decides the triage level + department
                      ├── pgvector       ← RAG embeddings, computed locally (no network)
                      └── Postgres       ← state, audit
```

Today the stack runs on Google (Gemini via Vertex, Cloud STT/TTS). The
deployment target is the workstation above, and it is reached through
config only — no code path changes:

### The endpoint contract (`.env`)

| Setting | Value on the workstation | Notes |
|---|---|---|
| `SCREENING_MODEL_PROVIDER` | `openai_compatible` | `vertexai` = Gemini (current) |
| `SCREENING_OPENAI_BASE_URL` | `http://<workstation>:8000/v1` | **required** for this provider — startup fails rather than falling back to api.openai.com |
| `SCREENING_OPENAI_API_KEY` | optional | sent as `Authorization: Bearer` if set |
| `SCREENING_MODEL_NAME` | the served model id (e.g. `Qwen2.5-7B-Instruct`, `typhoon2-8b`) | default is a Gemini id — must be overridden |
| `SCREENING_MODEL_TIMEOUT_S` | `30` | per call; every call is also wrapped in `ainvoke_with_timeout` |
| `STT_PROVIDER` / `STT_BASE_URL` / `STT_MODEL` | `openai_compatible` / `http://<workstation>:8000/v1` / `whisper-large-v3` | `POST /audio/transcriptions`, multipart |
| `TTS_PROVIDER` / `TTS_BASE_URL` / `TTS_MODEL` | `openai_compatible` / `http://<workstation>:8000/v1` / server's TTS model | `POST /audio/speech`, wants `wav` at 24 kHz |
| `TTS_LOCAL_VOICE_TH` / `TTS_LOCAL_VOICE_EN` | voice ids the TTS server exposes | |
| `SPEECH_HTTP_TIMEOUT_S` | `30` | |

**What the LLM server must support:** the four chat calls are structured
(`with_structured_output`), which on an OpenAI-compatible server means
`response_format: {{type: json_schema}}` or tool calling. vLLM supports both;
a bare Ollama `/v1` is less reliable — run the `AI Model (local inference)`
Postman collection against the server before go-live; it sends the exact
bodies below.

**Requests carry no session id, no auth identity, and no cookies** — each
call is a standalone completion. The server needs no state between turns and
keeps nothing that could be joined back to a patient.

## What leaves the backend, per call

| Call | What is sent | Identity class | Proven by |
|---|---|---|---|
| extraction | criteria catalog, pending question, chief complaint, **the utterance verbatim** | patient free text | `test_no_pii_in_prompts` |
| question | persona, last 2 exchanges (our lines with the name masked to `[NAME]`), chief complaint, known answers, the approved question | patient free text | `test_no_pii_in_prompts::test_recent_turns_mask…` |
| explain | persona, symptom summary, department, urgency, manual passages (RAG), `[NAME]` placeholder | patient free text | `test_no_pii_in_prompts` |
| gate:* | one short utterance + session language | patient free text | `test_no_pii_in_prompts` |
| surveillance | complaint category, present findings + values, slot answers — **not the transcript** | clinical findings only | `test_surveillance_extractor`, `test_no_pii_in_prompts` |
| STT | the turn's audio | **raw voice** | — (inherent) |
| TTS | the reply text, greeting includes the given name | **name** | — (inherent) |
| RAG embeddings | symptom summary → local HuggingFace model | never leaves the process | `rag_query.py` |

"Patient free text" means: whatever the patient chose to say. A name spoken
aloud goes through. That is the residual that only local hosting removes.

## What is stored

`ai_inference_audit` records the call site, model name, prompt version,
latency, whether it succeeded, the rules trace (finding ids, slot answers,
rule ids, RAG page hits) and any validator violations. **It does not store
prompts or completions.** The session state (`screening_sessions`) keeps the
findings with their evidence quotes and the symptom summary — at rest in the
hospital's own Postgres, shown to the nurse, never sent anywhere.

## The calls

One turn makes one extraction call, then either a question render or an
explanation. Gates fire only when the deterministic classifier is unsure;
surveillance runs once per completed session.
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

    parts.append("## The speech calls\n")
    for call in speech_calls():
        parts.append(f"### {call['title']}\n")
        parts.append(f"**When:** {call['when']}  \n**Carries:** {call['carries']}\n")
        parts.append(_fence(call["request"]))
        parts.append("\n**Reply:**\n")
        parts.append(_fence(call["response"], "json" if isinstance(call["response"], dict) else "text"))
        parts.append("")

    parts.append("## Running it against a workstation\n")
    parts.append(
        "The `AI Model (local inference)` Postman collection carries every "
        "call above as real requests. Set `LLM_BASE_URL` in the environment "
        "to the workstation and they run as-is — the same bytes the booth "
        "sends.\n"
    )
    return "\n".join(parts)


def build_postman_items() -> list[dict[str, Any]]:
    """Postman v2.1 items for the AI Model collection."""
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
            "url": pm_url("/chat/completions", "LLM_BASE_URL"),
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
    for call in speech_calls():
        path = "/audio/transcriptions" if call["id"] == "stt" else "/audio/speech"
        req = call["request"]
        if "multipart" in req:
            body = {"mode": "formdata", "formdata": [
                {"key": k, "value": v, "type": "file" if k == "file" else "text"}
                for k, v in req["multipart"].items()
            ]}
            header = []
        else:
            body = {"mode": "raw", "raw": json.dumps(req["json"], ensure_ascii=False, indent=2),
                    "options": {"raw": {"language": "json"}}}
            header = JSON_HDR
        items.append({
            "name": call["id"],
            "request": {
                "method": "POST", "header": header,
                "url": pm_url(path, "LLM_BASE_URL"), "body": body,
                "description": f"**{call['title']}**\n\n{call['when']}\n\nCarries: {call['carries']}.",
            },
        })
    return items
