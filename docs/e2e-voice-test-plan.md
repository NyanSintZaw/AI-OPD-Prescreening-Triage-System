# E2E Voice Test Plan — kiosk voice call (2026-07-27)

Automated Playwright runs against the real stack: native Postgres 16 + pgvector,
HIS mock (:8001), FastAPI (:8000, real Google STT/TTS/Gemini), Vite dev (:5173).
Reset between scenarios with `scripts/reset_demo.py --purge`.

## Method — how "voice" is tested deterministically

Real speech through the real pipeline, without a human:

- **Mic**: Chromium fake media stream with a **silent WAV** as capture file — the
  browser's real AudioWorklet pipeline runs, contributing only silence.
- **Speech**: utterances pre-synthesized with the backend's own Google TTS client,
  resampled to 16 kHz PCM. The test taps the app's live voice WebSocket (an
  init-script wrapper exposes it) and streams the PCM as binary frames — byte-for-byte
  what the mic path sends. STT, engine, TTS reply, playback, chips: all real.
- **Turn ending — both modes under test**:
  - *Done button*: stream speech, then click the real "I'm finished speaking" button.
  - *Auto-detect*: stream speech + ≥2.5 s of silence frames; the server's silence
    fallback must end the turn with no tap.
- **Assertions**: user-visible UI (assistant bubble, `You:` echo, chips, status
  chip, screens) plus a page-side log of JSON frames (identity, resume_choice,
  question_options, measurement_request, assessment_complete).

Known limit: WS-level injection bypasses the client-side mute gate, so the
client pre-roll ring is not exercised end-to-end (its behavior is asserted at the
hook level); the server-side mute/turn cycle — where every live freeze so far has
lived — is fully exercised.

## Scenarios (happy paths)

| # | Scenario | VN | Steps | Must hold |
|---|---|---|---|---|
| A | First-time spoken history intake | …004 (Waraporn, EN) | English → VN → spoken "Yes, that's me" → 5 history Qs: mix spoken answer + chip taps | Qs asked one-by-one in the same call; chips per Q; after Q5 → "what symptoms bring you in"; HIS HN record gains history; badge flips Returning |
| B | BP crisis → 15-min rest | …001 (สมชาย, EN) | ear-ache complaint (spoken) → answer red-flag Qs → BP card → type 190/115 | Rest prompt spoken, call ends politely, `bp_rest_windows` row open; assessment saved not emergency |
| C | Resume exactly where left off | …001 continuing B; plus a hang-up mid-interview on …002 | expire rest lock via SQL → re-enter VN → spoken identity → continue | Identity asked FIRST; continue/start-over chips only after yes; resume speaks the **pending question / re-opens BP card** — not the greeting; earlier findings intact in state |
| D | Finished patient cannot rescreen | any completed run | complete a run (decline follow-up → slip) → re-enter same VN | "Prescreening already complete" notice; one button → VN entry; auto-return ≈15 s; **no** session adoption, no call opened |

## Unhappy paths

| # | Case | Expected |
|---|---|---|
| U1 | Tap Done having said nothing | Spoken "Sorry, I didn't catch that" — never a frozen "Thinking…" |
| U2 | **Tap a chip, then answer the next question by voice + Done** | The spoken answer is transcribed and advances the flow (regression: tap left server muted → voice lost) |
| U3 | Wrong person on resume: identity → "No" | Bounced to VN entry; original session untouched (re-enter → identity gate again, state intact) |
| U4 | Unclear identity answer ("I'm not sure") | Re-asks (bounded retries), never interviews an unverified identity |
| U5 | Re-enter VN during active rest window | Blocked with countdown; other patients unaffected |
| U6 | Noise-only turn ended by silence fallback | First miss silent (grace), second prompts didn't-hear; no freeze |
| U7 | Finished VN + do nothing on notice | Auto-returns to VN entry on its own (timeout) |

## Pass criteria

Every step's expected UI state reached within timeout; no turn ever leaves the
kiosk stuck in "Thinking…"; server logs free of unhandled exceptions; DB
assertions (rest window, session status, HIS history) hold.

Artifacts: screenshots per failure + per-scenario WS frame log under
`e2e/out/`.

## Run log — 2026-07-27 (all green)

```
# stack: native postgres 16 + pgvector (~/pgdata-e2e), his-mock :8001,
# uvicorn :8000, vite :5173. Fresh: reset_demo.py --purge
cd hospital-hotline-assistant-api && uv run python ../e2e/gen_speech.py   # once
cd e2e
node a_history.mjs                    # A + U1 + U2            → PASS
node b_bp_rest.mjs                    # B                      → PASS
node c_resume.mjs blocked             # C part 1 + U5          → PASS
#   psql: UPDATE bp_rest_windows SET rest_until = now() WHERE resolved_at IS NULL;
node c_resume.mjs resume              # C part 2 + farewell    → PASS
node d_finished.mjs                   # D + U7 (14.9 s return) → PASS
node u_unhappy.mjs setup && node u_unhappy.mjs verify   # U3/U4 → PASS
```

U6 (noise-turn two-strike grace) is covered at unit level
(`test_empty_transcript_on_silence_fallback_stays_quiet_once`), not E2E.

**Bug found and fixed by this run**: with the mic open and the patient
silent (reading chips, thinking), the turn buffer grew without bound; past
60 s Google's sync STT rejected the whole turn ("400 Sync input too long")
→ spoken "something went wrong" loop, and short answers drowned in the
leading silence. Fix in `voice_bridge.send_audio`: pre-speech audio keeps a
~1 s rolling tail (`LEAD_SILENCE_KEEP_BYTES`), hard cap lowered to 55 s
(`MAX_TURN_BUFFER_BYTES`) — Google's limit is a hard 1 min. Unit test:
`test_lead_silence_stays_bounded`.

Also learned (by D failing first): a session only flips to `completed` when
the kiosk UI reaches the result screen — the client commits it. Tests (and
any monitoring) must not treat the `assessment_complete` frame as completion.
