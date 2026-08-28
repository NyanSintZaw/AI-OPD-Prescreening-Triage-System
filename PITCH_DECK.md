# Pitch Deck Guide — AI OPD Pre-Screening Booth

**คู่มือทำสไลด์นำเสนอ — บูธคัดกรองผู้ป่วยนอกด้วย AI**

A build guide for a **9-minute, two-presenter, Thai + English** pitch of the MFU AI OPD
pre-screening booth. It follows the required structure (Problem & ROI → Live Demo →
Business Model → Deployment Prep) and tells you, per slide: what goes on it, who says it,
in which language, and where the content comes from in this repo.

> **Read the source docs while you build:** `PROJECT_OVERVIEW.md` (plain-language what/why),
> `docs/features.md` (the *what*, by surface), `docs/demo-runbook.md` (the five demo runs),
> `docs/demo-script-meeting-2026-07.md` (exact words to speak), `docs/his-integration.md`
> (the 7-day MFU data + write-back model), `docs/hospital-integration-security.md`
> (production security + local-inference decision), `docs/ai-quality-evaluation.md` (measured
> quality numbers).

---

## 0. Ground rules before you open the slide editor

1. **Nine minutes is ~14 slides.** Anything past 16 will make you rush the demo, which is
   the half that actually sells. Cut slides, not demo time.
2. **Every number on a slide must be traceable.** Numbers that exist today: the MFU 7-day
   export (11,624 encounters, 3,072 walk-ins, 11 routable departments = 64% of routed
   encounters) and the extraction eval (71/71 corpus, 11/11 volunteered denials). Numbers
   that do **not** exist yet — nurse-minutes per patient, queue length, licence price — are
   marked `[FILL]` in §3 and §5 below. **Do not invent them on a slide.** Measure them at
   MFU, or state them as an assumption in visible text on the slide.
3. **The two-presenter split is a feature, not an accident.** Say it out loud in the first
   15 seconds ("we'll alternate Thai and English — same content, no repetition") so the
   audience does not spend two slides waiting for a translation that never comes.
4. **Never translate a slide twice.** One language owns the slide body; the other language
   appears only as a short subtitle line. Repeating everything in both languages doubles
   the reading time and halves the pace.

### The two-presenter model (recommended)

| Section | Lead presenter | Spoken language | The other presenter does |
|---|---|---|---|
| 1. Problem & ROI | **TH** | Thai | one English sentence on the ROI headline |
| 2. Demo — Scenario A (patient flow) | **TH** | Thai (kiosk set to ไทย) | narrates in English over the Thai audio |
| 2. Demo — Scenario B (the "Aha") | **EN** | English (kiosk set to English) | drives the mouse / keyboard |
| 3. Business Model | **EN** | English | one Thai sentence on onboarding |
| 4. Deployment Prep | **EN** | English | Thai answers on hospital-side items |
| Q&A | both | answer in the asker's language | — |

Why this split: the **patient-facing** half is genuinely Thai (that's the real user), and
the **commercial/technical** half is the language the hospital IT and procurement side
reads its contracts in. It also gives each presenter one continuous 3–4 minute block
instead of ping-ponging every slide.

**Alternative if one presenter is far stronger:** the strong presenter takes §1 + §2 (the
first 5:30, where attention is highest), the second takes §3 + §4. Same rule — no
sentence gets said twice.

### Slide text rules for a bilingual deck

- Headline: **Thai large, English small underneath** (or the reverse, consistently) — pick
  one and never flip it.
- Body bullets: **one language only**, the language the presenter is speaking on that slide.
- Numbers, department names, and product names: keep the HIS's verbatim Thai
  (e.g. `แผนก OPD HEART (หน่วยตรวจหัวใจและหลอดเลือด)`) — it proves you read their data.
- Fonts: pair a Thai face (Noto Sans Thai / Sarabun / IBM Plex Sans Thai) with its Latin
  sibling; Thai at ~1.05× the Latin size so they optically match. Test the deck on the
  actual projector — Thai tone marks are the first thing to disappear at low contrast.
- Brand: reuse the kiosk's own tokens from `hospital-hotline-assistant-web/src/styles/tokens.css`
  (`--mch-cyan` etc.) so the deck and the live demo look like one product.

---

## 1. The Problem & ROI — 1:30 · 3 slides · TH lead

### Slide 1 — The Hook (0:30)

**One sentence + one number. No bullets.**

- Thai headline: **"ทุกคนที่เดินเข้า OPD ต้องรอให้คนถาม ก่อนจะรู้ว่าต้องไปห้องไหน"**
  (English subtitle: *"Every OPD walk-in waits for a human to ask before anyone knows where they belong."*)
- The metric it drags down — pick **one** and put it huge:
  - **`3` minutes** of nurse time per walk-in spent on the same intake questions, **or**
  - **`` minutes** average wait before a walk-in is routed.
  - Anchor it with what you *do* have: **3,072 walk-ins in 7 days** at MFU (≈ **440 per day**)
    from the `Prescreen_7Day` export — that is the population the booth serves.
- Visual: one photo of an OPD queue, or a simple bar showing 11,624 encounters split into
  8,552 appointments (grey) vs 3,072 walk-ins (highlighted). *The highlighted bar is your market.*

> Presenter note (TH): open with the friction, not the technology. Do not say "AI" yet.

### Slide 2 — The Solution in one line (0:30)

- Thai headline: **"ผู้ป่วยคุยกับบูธ 2 นาที — ระบบรู้ว่าเร่งด่วนแค่ไหน และต้องไปแผนกไหน ก่อนถึงเคาน์เตอร์"**
- Three icons, three words only: **พูด (Speak) → คัดกรอง (Triage) → ไปแผนก (Route)**.
- One trust line, in a box: **"พยาบาลตรวจทุกเคส — AI ไม่เคยเป็นคนตัดสินสุดท้าย"**
  (*A nurse reviews every case — the AI never has the final word.*) Put this on slide 2,
  not slide 12. In a hospital room, the safety objection forms in the first 30 seconds; kill
  it early or you present the rest of the deck to a distracted audience.

### Slide 3 — The ROI outcome (0:30)

- Headline shape: **"Cut front-desk intake time by `[FILL]`% — `[FILL]` nurse-hours back per month."**
- Show the arithmetic on the slide, in three cells, so it is auditable at a glance:

  ```
  440 walk-ins/day  ×  [FILL] min saved each  =  [FILL] nurse-hours / month
  ```

- Add the second, harder-to-price benefit as a one-liner: **emergencies are caught in the
  queue, not at the counter** — a dangerous BP reading or a red-flag symptom ends the
  interview on turn one and sends the patient to ER immediately.
- **Honesty slide-note (put it in small text, say it out loud):** "the per-patient minutes
  are from a `[FILL]`-patient time study at MFU on `[FILL]`" — or, if you have not run one,
  "illustrative; we propose measuring this in the pilot." A hospital audience will ask, and
  an admitted assumption is far stronger than a confident guess.

**How to get the `[FILL]` numbers before the pitch (worth doing — it is one afternoon):**
stand at the OPD front desk, time 20–30 walk-ins from "patient reaches staff" to
"patient is told which department", and count how many of those minutes are intake
questions the booth already asks. That single measurement turns your whole ROI section
from a claim into a finding.

---

## 2. The Live Demo — 4:00 · runs from `docs/demo-runbook.md`

**This is 45% of your time. Rehearse it until it is boring.** Two scenarios only. Do not
tour the settings, the criteria editor, or the admin metrics page — they are §4 material at
best, and a Q&A answer at worst.

### Pre-flight (do this before the audience is in the room)

From `docs/demo-runbook.md` §0 and `docs/demo-script-meeting-2026-07.md` §0:

1. `docker compose up -d` (Postgres :5432 + mock HIS :8001), plus
   `docker compose up -d --force-recreate his-mock` for a **pristine reseed** — a
   half-used demo dataset is the #1 live-demo failure.
2. Backend `uv run uvicorn app.main:app --reload`; frontend `npm run dev`.
3. **Three browser tabs, already logged in**, arranged before you start:
   Kiosk `/kiosk` · Nurse `/nurse` · Admin `/admin`.
4. `VITE_ENABLE_VOICE=true`, Google STT/TTS credentials present, and a **10-second mic
   check** ("hello" → words appear → reply is heard).
5. Optional but high-value: upload the triage manual PDF in **Admin → Triage Manual** so
   the spoken explanation cites real manual phrasing.
6. **Record a screen capture of both scenarios the day before.** If the mic or the room
   audio fails, you play the video and keep talking — you lose nothing. The chat fallback
   in the runbook also works, but the voice behaviour is the point, so prefer the video.

### Scenario A — the day-to-day workflow (≈2:00, Thai, TH presenter)

Use **Run 1** from the runbook: VN `990000000000000004`, Waraporn Srisuk (~33) → routine → General OPD.

What the audience must see, in this order:

| Beat | On screen | The one line to say |
|---|---|---|
| 1 | Patient enters/scans VN; booth **greets by name** | "ระบบดึงข้อมูลจาก HIS ของโรงพยาบาลเอง — ไม่ต้องกรอกอะไรใหม่" |
| 2 | Spoken identity confirmation | "ยืนยันตัวตนก่อนเสมอ" |
| 3 | Patient **speaks** symptoms; AI asks follow-ups aloud; quick-reply chips visible | "ตอบด้วยเสียงหรือแตะก็ได้" |
| 4 | **BP is deliberately skipped** (ENT-like complaint, under 60); weight/height taken | "ระบบวัดเฉพาะที่จำเป็นทางคลินิก ไม่ได้วัดทุกอย่างกับทุกคน" |
| 5 | Result screen: department + floor/room + map + printable slip | "ผู้ป่วยได้แผนกและทางเดิน — แต่ไม่เห็นระดับความรุนแรง" |

**The point of Scenario A is ordinariness.** Say the word "normal" — most patients are not
emergencies, and the booth's job for them is to be fast and unremarkable. Resist narrating
the architecture here.

If you have 20 spare seconds, land the safety-by-design detail while the result screen is
up: the patient is never shown a level, colour, diagnosis, or prescription — every reply is
machine-validated against leaks in both Thai and English before they hear it.

### Scenario B — the "Aha!" (≈2:00, English, EN presenter)

Use **Run 3**: VN `990000000000000005`, ประเสริฐ สุขสม (~78) → measured BP → **Emergency**.

This is the slide-less centrepiece. Two halves:

**B1 — the catch (≈1:00).** Elderly patient, complaint sounds mild, cuff reads dangerously
high → the system **disposes to emergency immediately**, mid-interview. The line to say:
*"The objective reading is merged into the state **before** the red-flag gate — so a
dangerous vital ends the interview on turn one, no matter how the conversation was going."*
This is the capability nobody else in the room has: the booth catches the patient the
front desk would have put in a chair.

**B2 — the automated action + the audit (≈1:00).** Switch to the **nurse portal** tab. Show:

- the case waiting for review with the full picture — transcript, severity level, the
  vitals, the recommended department;
- the **reasoning with citations back to the hospital's own triage manual**;
- the nurse confirms → **Stage 2 write-back** puts the destination and SBAR handover into
  the hospital record and returns a queue number. (Stage 1 — the booth's measurements —
  already wrote itself the moment the patient finished.)

The sentence that closes the demo: *"The model reads language. The decision is made by
deterministic, versioned rules encoded from your own manual — same input, same answer,
every time, and every decision traces to the rule that fired."* Then stop talking and go to
slide 4. Do not add a third scenario.

**Explicitly skip:** criteria upload/approve workflow, AI metrics dashboard, disease
surveillance, desktop widget, database-settings screen. Have a one-line answer ready for
each in case it is asked (see §6).

---

## 3. Business Model & Value — 1:30 · 3 slides · EN lead

Nothing in this repo sets prices. The structure below is what a hospital procurement
committee expects to see; **you fill the numbers**, and the tier boundaries should follow
the product's real seams (kiosks, seats, and whether inference is on-prem).

### Slide 4 — Pricing structure (0:40)

A three-tier table, one column per tier, five rows max:

| | **Pilot** | **Department** | **Hospital-wide** |
|---|---|---|---|
| Booths (kiosks) | 1 | up to `[FILL]` | unlimited |
| Staff seats (nurse + admin) | `[FILL]` | `[FILL]` | unlimited |
| Inference | cloud (Vertex) | cloud or on-prem | **on-prem, local LLM/STT/TTS** |
| HIS write-back | read-only | Stage 1 + 2 | Stage 1 + 2 + assignments API |
| Price | `[FILL]` THB / `[FILL]` mo | `[FILL]` THB / yr | `[FILL]` THB / yr |

Design decisions worth stating on the slide:
- **Per-booth licence + per-seat for staff portals** is the natural fit — the booth is the
  unit of clinical throughput, the portal is the unit of staff access.
- **Usage-based is a bad fit here and you should say why**: a per-conversation price makes
  the hospital hesitate to screen patients, which is the opposite of the safety outcome.
  Saying this unprompted signals you understand the buyer.
- **Onboarding**, as a separate line: criteria encoding from the hospital's own manual,
  HIS integration, booth installation + device pairing, and staff training — priced as a
  one-time engagement `[FILL]`, because it is real work (the criteria are hand-encoded and
  nurse-approved, not configured).

### Slide 5 — The business case (0:40)

One table, three rows, annual figures. This is the slide procurement photographs.

```
Annual platform cost                    [FILL] THB
Onboarding (year 1 only)                [FILL] THB
─────────────────────────────────────────────────
Nurse time recovered   [FILL] hrs × [FILL] THB/hr   =  [FILL] THB
Net year-1 value                        [FILL] THB     (payback in [FILL] months)
```

Then one line of benefits you deliberately do **not** price, so the audience knows you
were conservative: earlier emergency detection, structured chief complaints in the record
instead of free text, a complete audit trail per session, and disease-surveillance data as
a by-product.

### Slide 6 — Why us / why now (0:10, or merge into 5)

Three bullets: the criteria are **already encoded** from the MFU manual and version-managed;
the integration is **already built** against a faithful mirror of MFU's own `Prescreen`
export; production is designed to run **entirely inside the hospital** (see §4).

---

## 4. Deployment Prep Checklist — 2:00 · 3 slides · EN lead, TH answers hospital-side items

Frame this section as **"here is what we need from you, and here is what we've already
done"** — a two-column layout on every slide (Us / You). It converts a checklist into a
demonstration of readiness.

### Slide 7 — Technical (0:40)

- **Identity / SSO:** today the portals use in-memory bearer tokens with roles
  (`super_admin` / `nurse` / `viewer`) — tokens are revoked on logout and vanish on restart.
  **Ask on the slide:** does the hospital want **SSO/SAML or OIDC against the hospital IdP**
  (AD FS / Azure AD)? Decision needed: IdP type, group→role mapping, session lifetime.
  *State plainly that this is a build item, not a shipped feature — an over-claim here is
  discovered in week one of the pilot.*
- **Network & allowlisting:** the booth sits **on the hospital LAN** (kiosk hardware is
  on-premises anyway). Required flows: booth → HIS integration API (mTLS/TLS), staff
  browsers → portal. Egress to Google Cloud is needed **only while running cloud inference**
  — the on-prem build removes it entirely.
- **Environments:** staging (against `hospital-his-mock` or a hospital-provided test API) →
  production. Ask for a **HIS test endpoint + test visit IDs**; that single item is usually
  the long pole.
- **Secrets:** API credential moves out of `.env` into managed secret storage, masked in UI.
- **Audit:** outbound-request log (timestamp, operation, hashed visit id, result) for
  reconciliation against the hospital's own gateway logs.

### Slide 8 — Data & integration (0:40)

Put the **three-operation table** on the slide verbatim — it is the most reassuring artifact
you own, because it shows how *little* crosses the boundary:

| Operation | Direction | Data |
|---|---|---|
| `GET /api/visits/{visit_id}` | read | visit id, name, birthdate, appointment flag, existing vitals |
| `POST /api/visits/{id}/prescreen` | write (Stage 1) | booth measurements + booth id + held narrative |
| `POST /api/v1/patient-assignments` | write (Stage 2) | **nurse-confirmed** destination + SBAR → returns queue number |

Say the two sentences that answer the question they are actually worried about:
**"We never connect to your database. You expose a small API, you choose the fields, and
you can revoke us without touching the DB."** And: **"A visit is only looked up when the
patient themselves enters their own visit ID at the booth — we never enumerate visits."**

Data items to request, as a checklist:
- The **triage manual** (PDF) — it is what the criteria and the cited explanations are built from.
- A **prescreen export sample** for benchmarking — MFU already shared a 7-day file
  (11,624 encounters); the real file stays out of git, a synthetic sample ships in
  `hospital-his-mock/sample_visits.csv`.
- The **department list, verbatim**, with the hospital's own Thai names — 11 are currently
  routable (≈64% of routed encounters); the rest are catalogued as known destinations but
  deliberately not triage outcomes.
- Test visit IDs + a named clinical owner who signs off criteria versions.

### Slide 9 — Hardware (0:40)

Lead with the decision, because it is the privacy answer: **production runs local LLM,
local STT, and local TTS on hospital hardware, so patient audio and symptom narratives
never leave the building.** Cloud (Vertex Gemini) is a demo artifact; the model access is
behind an adapter, so the swap is configuration, not a rewrite.

Present hardware as **three line items with a spec column to be finalised from the pilot's
concurrency target** — and say that out loud rather than quoting a GPU model you have not
benchmarked:

| | What it runs | Sizing driver | Spec |
|---|---|---|---|
| **Inference server (GPU)** | local LLM + STT + TTS | peak **concurrent calls**, not daily volume; each call is one bounded turn-by-turn pipeline | `[FILL]` — decide from a concurrency benchmark; VRAM must hold the chosen Thai-capable model + STT + TTS together |
| **Application server** | FastAPI backend, PostgreSQL + pgvector, portals | modest; CPU-bound | `[FILL]` CPU / `[FILL]` RAM |
| **Storage** | sessions, transcripts, audit trail, manual embeddings, retention window | retention policy `[FILL]` — an open question for the hospital | `[FILL]` GB + backup |
| **Booth (per kiosk)** | browser + mic/speaker + BP cuff (Bluetooth) + thermometer + slip printer | one per booth | mini-PC or all-in-one, touch screen |

**Be explicit about what you don't know yet:** the GPU spec should come from a concurrency
benchmark you propose running in the pilot, not from a number on a slide. Offer it as the
first deliverable of the engagement. If pressed for a figure in the room, give a range and
name the variable ("it depends on peak simultaneous conversations — one booth and eight
booths are different machines").

---

## 5. Closing + the numbers you must collect first

### Slide 10 — The ask (whatever seconds remain)

One slide, three lines: **what you want next** (a pilot on `[FILL]` booth(s) at OPD for
`[FILL]` weeks), **what you need from them** (test HIS endpoint, manual, clinical owner),
**what they get** (the measured baseline that turns §1's `[FILL]`s into real numbers).

### The `[FILL]` register — assign an owner and a date to each

| # | Number | Where it goes | How to get it |
|---|---|---|---|
| 1 | Minutes of staff time per walk-in intake | Slide 1, 3, 5 | Time 20–30 walk-ins at the OPD front desk |
| 2 | Nurse hourly cost | Slide 5 | Hospital HR / finance |
| 3 | Average walk-in wait before routing | Slide 1 | Queue system export, or the same time study |
| 4 | Licence prices per tier + onboarding | Slide 4, 5 | Your decision — bring it decided, not "TBD" |
| 5 | Peak concurrent booth conversations | Slide 9 | Estimate from 440 walk-ins/day + arrival peaks |
| 6 | GPU spec | Slide 9 | Concurrency benchmark (propose as pilot deliverable) |
| 7 | Retention window for audio/transcripts | Slide 9 | Hospital privacy officer — an open question in the security doc |

**Never ship the deck with a visible `[FILL]`.** Either the number, or the sentence
"to be measured in the pilot" — both are fine; a bracket on the projector is not.

---

## 6. Q&A prep — the questions this room always asks

Prepare each answer in **both languages**, ~2 sentences, and decide in advance who takes it.

| Question | The short answer |
|---|---|
| **"What if the AI is wrong?"** / "ถ้า AI ตัดสินผิดล่ะ" | The AI does not decide. It extracts findings from speech; deterministic rules encoded from your manual decide the level and department, and a nurse reviews every case before anything is published to the record. |
| **"Does it diagnose?"** | No — it routes and prioritises. Patients never see a level, colour, diagnosis, or prescription; replies are validated against leaks in both languages. |
| **"Where does patient audio go?"** | In production, nowhere — local LLM/STT/TTS on hospital hardware. In this demo it uses Google Cloud, and no patient identifier is ever sent to the model (enforced by a test that fails the build). |
| **"Elderly patients won't use a kiosk."** | Every question also renders tappable quick-reply chips, and a typed fallback exists. Staff assistance is unchanged — the booth removes intake work, it does not remove people. |
| **"How do we change the criteria?"** | Upload → draft → review → approve → activate, with version numbers; each session records the version it used, so old results stay auditable. It is a governance change, not a code change. |
| **"Thai accents / dialects?"** | Show the Thai run (Run 5, VN `…008`) if not already shown; be honest about coverage and offer accent testing as a pilot task. |
| **"What happens if the network or the HIS is down?"** | Say what is true today and what is planned — do not improvise. Verify the current behaviour before the pitch. |
| **"Can we see the AI's reasoning for one case?"** | Yes — per-session trace in the admin portal shows what the model saw and which rule fired at every step. (Have this tab open but do not show it unprompted.) |

---

## 7. Build checklist for the deck itself

- [ ] Slide count ≤ 16; timings written in the speaker notes of every slide
- [ ] Presenter split marked on each slide (`TH` / `EN` badge in the corner of the notes)
- [ ] Every number traced to a source, or labelled as an assumption **on the slide**
- [ ] Demo rehearsed end-to-end **three times**, including a from-cold service start
- [ ] Screen recording of both scenarios saved locally as the failure fallback
- [ ] Pristine HIS reseed run immediately before the pitch
- [ ] Mic check done in the actual room, with the actual audio setup
- [ ] Both presenters can deliver the other's section — one person gets sick
- [ ] Handoff sentences written and rehearsed (the two riskiest seconds in the whole pitch)
- [ ] Leave-behind: a one-page PDF with the three-operation integration table, the hardware
      line items, and the pricing tiers — that page is what circulates after you leave

### Handoff lines (write them down, they are always improvised badly)

- TH → EN, into the demo's Scenario B: *"ตอนนี้ให้ `[name]` พาดูเคสที่ระบบจับได้เอง"* →
  EN picks up: *"Same booth, different patient — watch what happens when the numbers disagree with the conversation."*
- EN → TH, into Q&A: *"We'll take questions in either language — `[name]` for the clinical
  and hospital-side ones, me for the technical."*
