# Demo Script — July 17 Meeting Requirements

Six scenarios that walk through every new requirement, in a natural order for
a live audience. Each scenario lists: who plays the patient, the exact words
to speak (🎙 = say into the mic; ⌨ = type/tap on screen), what the system
must do, and where to point the audience afterwards (nurse portal / admin
Database tab / hospital DB).

> **Covers:** VN name confirmation with natural-language reprompt · vitals
> always recorded · weight/height skipped when a recent HN measurement exists
> (and re-asked when stale) · BP crisis → 15-minute re-measure lock that
> survives other patients using the booth · session resume on same-VN
> re-entry · first-time-patient history intake written to the HN record *and*
> feeding the assessment · natural-language chief complaint · slip navigation
> line · admin Database VN/HN tabs.

---

## 0. Pre-flight (5 minutes before the demo)

1. Services:
   ```bash
   docker compose up -d                     # postgres :5432 + mock HIS :8001
   docker compose up -d --force-recreate his-mock   # ← pristine reseed (see Appendix A)
   # free port 8000 if another project holds it, then:
   cd hospital-hotline-assistant-api && uv run uvicorn app.main:app --reload
   cd hospital-hotline-assistant-web && npm run dev  # :5173
   ```
2. Open three browser tabs:
   - **Kiosk** — `http://localhost:5173/kiosk`
   - **Nurse** — `/nurse` (opd.nurse@mfu.local / nurse1234)
   - **Admin** — `/admin` (ops.admin@mfu.local / admin1234) → **Database tab**;
     if not connected, connect endpoint `http://localhost:8001`, name e.g.
     "MFU Medical Centre HIS".
3. In the admin Database tab, show the **Patients (HN)** tab once: 8 HN
   records, 5 marked **Returning** (with history), 3 **First-time**. This is
   the "before" snapshot the whole demo plays against.
4. Mic + speakers checked; UI language Thai unless a scenario says English.

### The cast (seeded data)

| VN (visit) | HN | Name | Age | Seeded state | Used in |
|---|---|---|---|---|---|
| …000000001 | 09900001 | สมชาย ใจดี | 41 | Returning · HTN, smoker · **recent** weight/height (5 Jul) | S1, S2 |
| …000000002 | 09900002 | สมหญิง รักษาดี | 68 | Returning · diabetes, penicillin allergy · recent w/h | S1 (wrong VN) |
| …000000004 | 09900004 | Waraporn Srisuk | 33 | **First-time** (no history yet) | S3 |
| …000000005 | 09900005 | ประเสริฐ สุขสม | 78 | Returning · COPD + heart disease, heavy smoker · **stale** w/h (Sep 2025) | S4 |
| …000000007 | 09900007 | มาลี วงศ์สว่าง | 51 | Returning · asthma, sulfa allergy · recent w/h | S5 |
| …000000006 | 09900006 | Anucha Thongdee | 24 | First-time (English name) | S5 (intervening patient) |

Type only the **full VN** at the kiosk (e.g. `990000000000000001`).

---

## S1 — "Is this you?" VN confirmation + natural-language reprompt (≈3 min)

**Requirement:** after VN entry the system confirms the patient's full name;
saying "no" in natural language sends them back to re-enter the VN.

**Story:** สมชาย mistypes his VN and gets someone else's record.

| # | Step | Speak / type | Expected |
|---|---|---|---|
| 1 | Tap **ไทย** on the language screen | — | VN entry screen |
| 2 | ⌨ Enter the **wrong** VN `990000000000000002` | — | Confirm screen: **"คุณคือ สมหญิง รักษาดี ใช่ไหม?"** with ใช่/ไม่ใช่ buttons **and** a free-text box |
| 3 | ⌨ Type in the text box: **`ไม่ใช่ครับ คนละคน`** | — | Classified as "no" → visit **unlinked**, kiosk returns to VN entry ("please re-check your number") |
| 4 | ⌨ Enter the **correct** VN `990000000000000001` | — | "คุณคือ สมชาย ใจดี ใช่ไหม?" |
| 5 | ⌨ Type: **`ใช่ครับผม`** (don't use the button — show natural language works) | — | Confirmed → continues (สมชาย is returning, so no history form) → conversation starts |

**Tell the audience:** the reply is classified by the same bilingual NLU the
interview uses — "no, wrong person", "ไม่ใช่ค่ะ", "yes that's me" all work; an
ambiguous reply ("ไม่แน่ใจ") re-prompts instead of guessing. A reply that
carries content ("ไม่ใช่ค่ะ ฉันชื่อมาลี") also re-prompts — it never guesses.

*Keep this session running — S2 continues it.*

---

## S2 — Returning patient: vitals always, weight/height skipped, natural CC, slip navigation (≈5 min)

**Requirements:** vitals are always recorded; weight/height omitted because a
recent measurement exists; chief complaint reads like a sentence; slip prints
"Please proceed to …, 3rd Floor."

**Story:** สมชาย (41) has had an earache for two days. Note: before this
change, BP for an ear complaint was only asked at age ≥ 60 — สมชาย is 41 and
now gets it anyway.

| # | Step | Speak | Expected |
|---|---|---|---|
| 1 | Greeting plays ("สวัสดีค่ะ คุณสมชาย …") | 🎙 **"ปวดหูข้างขวามาสองวันครับ"** | Ear complaint template selected |
| 2 | Red-flag / associated questions (hearing loss, discharge, fever…) | 🎙 answer naturally — **when asked about ear discharge say "มีน้ำใส ๆ ไหลออกจากหูนิดหน่อยครับ"**, others "ไม่มีครับ" | Interview proceeds. *(The discharge answer matters: ENT direct-routing requires a specialty finding — deny everything and the criteria correctly route to general OPD instead, verified live July 22.)* |
| 3 | **BP request appears** ("กรุณาวัดความดันโลหิต…") | ⌨ use the cuff, or type a normal reading e.g. **`118/76` pulse `72`** | Reading accepted — *point out: age 41, ear complaint, BP still required (new rule)* |
| 4 | Any remaining slot questions (severity, character…) | 🎙 short natural answers, e.g. **"ปวดตุบ ๆ พอทนได้ครับ"** | — |
| 5 | **Watch what does NOT happen** | — | **No weight/height question** — HN 09900001 has 72.5 kg / 172 cm measured 5 Jul (recent < 90 days), pre-filled from the hospital DB |
| 6 | Disposition + follow-up offer | 🎙 **"ไม่มีแล้วครับ ขอบคุณครับ"** | Routed to **OPD ENT**; slip opens |

**Show on the slip:** the navigation line — **"กรุณาไปที่แผนก OPD E.N.T (หู
คอ จมูก) ชั้น 3"** (EN: *"Please proceed to OPD ENT, 3rd Floor."*), plus the
pre-filled weight/height/BMI on the vitals block.

**Show in the nurse portal (review queue → this session):**
- **Chief complaint is a sentence** — "ปวดหู มา 2 วัน ก่อนมาโรงพยาบาล" style,
  not `"ปวดหู; findings: ear_pain; duration: 2 วัน"`.
- Risk factors from the HN record are already stamped without สมชาย saying a
  word about them: `hypertension_history`, `smoking` (from "Hypertension
  (diagnosed 2019)" / "smokes ~5 cigarettes/day" on his patient record).

**Show in admin → Database:** VN tab: visit …001 flipped **Registered →
Screened**, booth vitals written (Stage 1), weight/height carried from the
HN prefill. Optionally have the nurse confirm → status **Routed**, natural CC
published to `nurse_chief_complaint` (Stage 2).

---

## S3 — First-time patient: history intake → HN record → changes the assessment (≈6 min)

**Requirements:** first-time patients answer the 5 additional questions;
answers persist on the HN master record; and history **feeds the
assessment**, not just the chart. Also demonstrates the English flow.

**Story:** Waraporn (33, first visit ever) has hypertension and is 7 months
pregnant with a headache since morning — booth-collected history + her
complaint together trigger the pre-eclampsia rule.

| # | Step | Speak / type | Expected |
|---|---|---|---|
| 1 | Language: **English** → VN `990000000000000004` | — | "Are you **Waraporn Srisuk**?" |
| 2 | Tap **Yes** | — | **History intake form appears** (first-time only — สมชาย never saw it) |
| 3 | ⌨ Fill the 5 fields: | | |
|   | · Smoking / alcohol | **`Non-smoker, occasional wine`** | |
|   | · Allergies | **`Penicillin — rash`** | |
|   | · Chronic conditions | **`High blood pressure since 2023`** | |
|   | · Past surgeries | **`None`** | |
|   | · Family history | **`Mother has diabetes`** | Save → pushed to the hospital DB (HN record) |
| 4 | Conversation starts | 🎙 **"I'm seven months pregnant and I've had a bad headache since this morning."** | Pregnancy + headache extracted; `hypertension_history` already present **from the form she just filled** |
| 5 | — | — | **Emergency banner** — pregnancy + hypertension history = suspected pre-eclampsia, forced level 2, routed to Emergency. Staff notified. |

**Tell the audience:** the rules engine decided this, not the LLM — rule
`tt_pregnancy_hypertension` (MFU criteria, cited in the nurse trace) fires on
`pregnancy` + `hypertension_history`. Without the history intake she'd have
been an ordinary headache interview; the form she filled 60 seconds ago
changed her triage.

**Show in admin → Database → Patients (HN):** hit Refresh — Waraporn's badge
flipped **First-time → Returning**, all 5 history answers now on her HN
record. Re-enter her VN later: no form (she's known now). Nurse portal shows
the allergy ("Penicillin — rash") on the review.

---

## S4 — Hang-up mid-interview → same VN resumes; stale weight/height re-asked (≈5 min)

**Requirements:** re-entering the same VN continues the interview instead of
restarting; weight/height **is** asked when the HN measurement is too old.

**Story:** ประเสริฐ (78) starts describing stomach pain, then walks away
(gets called by a relative). He comes back and re-enters his VN.

| # | Step | Speak | Expected |
|---|---|---|---|
| 1 | Thai → VN `990000000000000005` → confirm **"ใช่ครับ"** | — | Conversation starts (returning patient — no history form) |
| 2 | Greeting | 🎙 **"ปวดท้องมาตั้งแต่เมื่อคืนครับ"** | Abdominal template; questions begin |
| 3 | Answer 1–2 questions | 🎙 e.g. **"ปวดแถวลิ้นปี่ครับ"** | — |
| 4 | **Walk away** — tap **Exit** → confirm, or just let the idle timer reset | — | Kiosk returns to attract screen. *Tell audience: session is still alive in the database.* |
| 5 | (Optional beat) another patient could use the booth now | — | — |
| 6 | ประเสริฐ returns: Thai → **same VN** `…005` | — | Kiosk finds his unfinished assessment and asks: **"ทำการประเมินต่อ หรือ เริ่มใหม่?"** — tap **ทำต่อ** → jumps straight back into the conversation; earlier answers intact. (Re-entering the VN of a *finished* assessment instead offers start-over + reprint slip.) |
| 7 | Finish the interview | 🎙 keep answering; BP when asked, e.g. **`135/82`** | — |
| 8 | **Weight/height IS asked this time** | ⌨ type e.g. **`58` / `165`** | *Point out the contrast with S2: his last measurement is from Sep 2025 — older than 90 days — so the booth re-measures* |
| 9 | Dispose + decline follow-up | 🎙 **"ไม่มีแล้วครับ"** | Slip with navigation line |

**Show in the nurse trace:** his COPD + heart-disease + smoking risk factors
stamped from the HN record on turn 1.

---

## S5 — BP crisis → 15-minute rest lock that survives other patients (≈6 min)

**Requirement:** after a too-high reading the patient must rest 15 minutes
before re-measuring; the timer is tied to the **patient**, not the kiosk
session — another patient can use the booth meanwhile, and the original
patient can re-measure the moment the window ends.

**Story:** มาลี (51) feels dizzy; her cuff reading is 190/115 — hypertensive
crisis.

| # | Step | Speak / type | Expected |
|---|---|---|---|
| 1 | Thai → VN `990000000000000007` → confirm | — | Conversation starts |
| 2 | Greeting | 🎙 **"เวียนหัว มึน ๆ มาตั้งแต่เช้าค่ะ"** | Headache/dizziness template; BEFAST stroke questions — answer 🎙 **"ไม่มีค่ะ"** to each |
| 3 | BP request | ⌨ type **`190` / `115`**, pulse `96` | **Rest-first flow**: the reading is treated as provisional (white-coat effect) — kiosk shows *"ความดันโลหิตสูง — กรุณานั่งพักก่อนค่ะ"* with the 15-minute instruction, the call ends politely, and the assessment is saved. No emergency yet, no conversation turn with the numbers. |
| 4 | Try to re-measure immediately (re-enter her VN → Continue → BP) | — | **Blocked**: rest countdown ("นั่งพักอีก XX นาที") with an "I'll come back" button. The window is keyed to **HN 09900007** |
| 5 | **Prove it's per-patient:** English → VN `990000000000000006` (Anucha, first-time — breeze through/skip the form) | 🎙 **"I have a sore throat."** …measure BP normally e.g. **`121/78`** | Anucha measures freely — the booth is not locked, only มาลี is |
| 6 | "15 minutes later" (demo shortcut — run in a terminal): | `psql "$DATABASE_URL" -c "UPDATE bp_rest_windows SET rest_until = now() WHERE resolved_at IS NULL;"` | Window expired |
| 7 | มาลี re-enters VN `…007` | — | Kiosk offers **"ทำการประเมินต่อ / เริ่มใหม่"** — tap Continue; the interview resumes; re-measure ⌨ **`142/88`** → proceeds normally to disposition |
| 8 | (Optional strong close) repeat with a still-high confirmatory reading, e.g. `192/118` | — | Now — and only now — the reading drives the rules: **level-2 emergency** (`dv_adult_bp_crisis`), staff alerted. Rest once, then decide. |

**Tell the audience:** the first out-of-range reading buys the patient a
15-minute rest (per the hospital's own re-measure protocol); only the
post-rest confirmatory reading may trigger the emergency rule. The lock
lives in Postgres (`bp_rest_windows`), keyed by HN — it survives kiosk
restarts, other patients, and hang-ups. In production the step-6 shortcut
simply doesn't exist; the clock runs out on its own.

---

## S6 — Close the loop: nurse confirm + the hospital's own database (≈4 min)

**Requirements shown:** natural-language CC published to the HIS; admin
Database **VN and HN tabs**.

1. **Nurse portal** → review queue → open สมชาย's assessment (S2):
   - chief complaint reads as a sentence; disposition reasons carry MFU
     manual citations; HN risk factors listed.
   - **Confirm** the routing → Stage 2 publishes to the hospital DB.
2. **Admin → Database → Visits (VN) tab:** visit …001 now **Routed** —
   `nurse_chief_complaint` and second location filled, exactly the columns of
   the hospital's real Prescreen export.
3. **Patients (HN) tab:** point at the whole journey in one screen —
   - สมชาย / ประเสริฐ / มาลี: *Returning*, seeded history, last measurement
     on file (สมชาย's from 5 Jul explains the skipped weigh-in),
   - Waraporn: flipped to *Returning* with the history collected **today**,
   - visit counts linking HN ↔ VN.

**Closing line:** "Everything the booth learned — measurements, history,
the nurse-signed complaint — landed in the hospital's own tables, staged
exactly like their iMed export: objective data at Stage 1, clinical narrative
only after a nurse signed it."

---

## Appendix A — Reset between rehearsals / demos

**One-shot reset (preferred):** from `hospital-hotline-assistant-api/`:

```bash
uv run python scripts/reset_demo.py           # retire sessions, clear BP locks, reseed HIS, restore first-timers
uv run python scripts/reset_demo.py --purge   # same + wipe ALL session data (empty nurse queue/dashboards)
```

Individual pieces, if you need finer control:

| Goal | Command |
|---|---|
| Pristine everything (HIS visits + HN history + first-time flags back to seed) | `docker compose up -d --force-recreate his-mock` |
| Reset visits only, keep collected HN history | `curl -X POST http://localhost:8001/api/admin/reset -H "X-API-Key: demo-his-key" -H "Content-Type: application/json" -d '{}'` |
| Also wipe HN history for the reset visits (re-demo first-time flow without full reseed) | same, body `{"visit_ids": ["990000000000000004"], "reset_history": true}` |
| Clear an active BP rest lock | `psql "$DATABASE_URL" -c "DELETE FROM bp_rest_windows;"` |
| Nurse queue / sessions | no reset needed — old sessions age out of view; leave as history |

## Appendix B — Rehearsal checklist & known behaviors

- **S3 step 4 was rehearsed live (2026-07-21)** — the exact sentence above
  produced level 2 via `tt_pregnancy_hypertension`, routed to Emergency, with
  a personalized emergency reply. Speak it close to verbatim; still do one
  dry run on demo day (LLM extraction is the one non-deterministic link).
- Speak in complete short sentences and pause; the booth ends your turn after
  ~2.5 s of silence.
- If STT garbles an answer, the engine re-asks red-flag questions exactly
  once — just answer again.
- "ไม่แน่ใจ" on any question is deliberately *not* recorded as no — the
  question repeats. Useful to show if asked about safety.
- The assistant never says a triage level/color to the patient — if an
  audience member asks "what level was that?", answer from the nurse trace.
- If the LLM explanation ever gets blocked by the validator you'll still get
  a clean template reply — nothing to handle live.
- Timing: full run ≈ 30 min. Shortest impressive subset: **S1 → S2 → S3**
  (≈ 15 min) covers confirmation, vitals policy, slip, history, and the
  assessment impact.
