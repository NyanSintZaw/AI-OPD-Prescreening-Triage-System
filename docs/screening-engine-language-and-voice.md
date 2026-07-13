# LangGraph Screening Engine — Language, Voice & Model

Answers three questions about the `TRIAGE_ENGINE=langgraph` engine (Stack C):
does it work in **both Thai and English**, in **both chat and voice**; how is
**patient input handled in a voice call**; and **which LLM** it uses. It also
states plainly what is and isn't tested.

---

## 1. Bilingual (Thai + English) — how it holds

Language is a **per-session lock**, set once and honored everywhere:

- **Where it's set.** The session is created with a `language` (`th` default
  or `en`). Text chat carries it on every request (`POST /sessions/{id}/chat
  [/stream]`, `payload.language`); voice carries it on the WebSocket
  (`/ws/voice/{session_id}?language=th|en`, validated to `{en, th}`).
- **The engine locks it.** `ScreeningTriageEngine._execute` sets
  `state.language = language` each turn; the language is never inferred from
  the utterance, so a Thai session stays Thai even if the patient drops an
  English word.
- **Everything downstream is bilingual by construction:**
  - Seed criteria (`app/data/screening_criteria_v1.json`) require both
    `text_en`/`text_th` on every question and both-language finding
    synonyms — pydantic rejects a criteria version missing either.
  - Deterministic template outputs (verbatim red-flag/scale questions,
    explanation fallback, voice greeting, escalation, "didn't catch that")
    exist in both languages, selected by `state.language`.
  - The output **validator enforces the reply language** (Thai-codepoint
    ratio): a Thai session can never emit an English reply past validation,
    and vice-versa — on top of the level/color/diagnosis/prescription leak
    checks, in both languages.

**Test coverage.** Golden end-to-end transcripts run full journeys in both
languages and validator-check **every** patient-facing reply
(`tests/screening/test_golden_transcripts.py`: EN cough, **TH chest-pain
emergency**, EN ENT-fail, EN pediatric). Rules/extraction tests include Thai
finding values.

---

## 2. Voice — same engine, both languages

Voice does **not** use a separate AI. With `VOICE_ENGINE=turn`, the
`TurnVoiceService` bridge (`app/services/screening/voice_bridge.py`) runs
each spoken turn through the **same** `process_chat_stream` pipeline as text
chat, so the deterministic engine drives voice too. The session language
flows into speech I/O:

- **STT** (`GoogleSttClient`) is called with the session language →
  `th → th-TH`, `en → en-US`.
- **TTS** (`GoogleTtsClient`) is called with the session language →
  `th → th-TH-Neural2-C` (Thai neural voice), `en → en-US-Neural2-F`.
- The greeting, "didn't catch that", and error lines are the localized
  templates.

**Test coverage.** `tests/screening/test_voice_bridge.py` includes a Thai
end-to-end turn asserting the greeting is Thai and that `language="th"`
reaches STT, the engine, and TTS — plus the English turn-flow, silence
fallback, emergency banner, and error-recovery tests.

### 2.1 How patient input is handled in a voice call

The browser streams **16 kHz mono Int16 PCM** up the WebSocket; replies come
back as **24 kHz PCM** frames. Per turn:

```
mic PCM 16 kHz ─▶ per-session buffer
                    │
   turn ends when EITHER:
     • client sends end_of_turn  (the "Send" button — the reliable path)
     • server silence fallback: ≥1.2 s of trailing quiet after speech
       (mean-abs amplitude < 250), or the 60 s buffer cap
                    │
                    ▼
   buffered PCM ─▶ WAV-wrap ─▶ STT(language) ─▶ transcript
                    │
     • empty transcript ─▶ speak localized "didn't catch that", keep listening
     • STT error       ─▶ speak localized error line
                    │
                    ▼
   transcript ─▶ process_chat_stream(input_mode="voice", language)
                    │  (same engine: extract → red-flag gate → question|dispose → explain)
                    ▼
   reply text ─▶ TTS(language) LINEAR16 24 kHz ─▶ 200 ms PCM frames ─▶ browser
```

Design points that matter:

- **Endpointing.** The **Send button is the reliable turn boundary**; the
  1.2 s trailing-silence fallback is a convenience, because Thai silence
  endpointing quality varies with mic/room. A short buffer (< 300 ms:
  breath, button-click bleed) is ignored.
- **Mic gating.** A client-driven `muted` flag (the client mirrors it and
  auto-unmutes after playback) is kept separate from an internal
  `processing` gate, so a silence-fallback turn never leaves the server
  muted with the client unaware.
- **Emergency banner** fires once, on a level-1/2 classification, over the
  JSON control channel — mirroring the live path — while the spoken reply
  still never states the level.
- **Persistence is per turn** (inside `process_chat_stream`) — no end-of-call
  transcript replay. Every turn writes the same rows a text turn does.
- **Robustness.** Three consecutive failed turns tear the call down; single
  failures speak a localized error and continue.
- **Trade-off vs Gemini Live.** Higher per-turn latency (STT→engine→TTS
  round-trip) instead of full-duplex streaming — accepted for the demo
  workstation, and the price of running voice through the deterministic
  engine.

---

## 3. Model: Gemini now, local LLM later (config-only swap)

The engine reaches the LLM through one construction point,
`model_adapter.build_chat_model(settings)`, whose contract is LangChain's
`BaseChatModel`. **Today it uses Gemini on Vertex AI** and will keep using
Gemini until a local model is ready — that switch is a **config change, not
a code change**:

| `screening_model_provider` | Backend | When |
|---|---|---|
| `vertexai` **(default)** | Gemini on Vertex AI (`screening_model_name`, default `gemini-3.1-flash-lite`, `thinking_level=minimal`, global endpoint), same ADC auth as the rest of the app | **Now / demo** |
| `openai_compatible` | Any OpenAI-compatible endpoint — vLLM or Ollama serving a local model (Typhoon/Qwen) via `screening_openai_base_url` | On-prem, later |

The LLM's role is deliberately narrow (decision separation): it only
**extracts** structured findings, **paraphrases** questions, and **phrases**
explanations. All triage/routing decisions are the pure rules engine, so the
model swap changes *wording quality*, not *clinical behavior*.

---

## 4. What is and isn't tested

**Verified by the automated suite** (green under both `TRIAGE_ENGINE=adk`
and `=langgraph VOICE_ENGINE=turn`; ~283 tests, only the pre-existing
env-dependent `test_rag_ingest` DSN check fails):

- Bilingual chat journeys, every reply validator-checked (goldens).
- Bilingual voice: Thai + English turn flow, language into STT/engine/TTS.
- Rules, extraction, disposition, question policy, validator, criteria
  governance, HIS adapters + write-back, vitals pre-fill.

**NOT yet tested — the live end-to-end.** No run has exercised the real
stack against a live Google (Vertex/STT/TTS) + a migrated Postgres. The
tests use fakes/`FakeChatModel`, so real Gemini extraction quality, real
Thai STT accuracy, and real TTS playback are **unproven until the demo
dry-run**. That dry-run is the outstanding step:

1. Apply migrations `012_bp_readings` → `015_departments_his_alignment`.
2. `uv run python scripts/seed_screening_criteria.py`.
3. Start the mock HIS (`hospital-his-mock`, port 8001) and the backend with
   `TRIAGE_ENGINE=langgraph VOICE_ENGINE=turn HIS_MODE=http
   HIS_BASE_URL=http://localhost:8001`.
4. Walk one Thai and one English conversation in chat; confirm one question
   at a time, no level disclosure, department + map shown, and the prescreen
   record appearing/updating on the HIS `/docs` side.
5. Repeat one call each in Thai and English for voice.
