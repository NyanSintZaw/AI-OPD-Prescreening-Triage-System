# Demo Runbook — AI OPD Pre-Screening (booth flow, **live call first**)

Five short patient runs, all on the **live voice call** — the primary path.
The patient enters a hospital visit ID; the booth greets them **by name**, then
the AI **talks** them through screening one question at a time (never showing a
triage level). Measurements happen **inside the conversation** when clinically
needed. The decision follows nurse-approved criteria — driven by what they
**say**, their **measured vitals**, and their **age** — and writes back to the
hospital DB in two stages, the second only after a nurse confirms.

The five runs are chosen so each isolates one idea:

| # | Visit ID | Patient (HIS) | Shows | Outcome |
|---|---|---|---|---|
| 1 | `990000000000000004` | Waraporn Srisuk (~33) | Named greeting, **quick-reply chips**, **BP intentionally skipped** (ENT-like, under 60), weight/height, **follow-up**, slip tab | routine → General OPD |
| 2 | `990000000000000003` | น้ำใส ใจเย็น (~8) | **Routing by age** (age auto from HIS) | child → Pediatrics |
| 3 | `990000000000000005` | ประเสริฐ สุขสม (~78) | **Routing by measured BP** (danger vitals) | elderly → **Emergency** |
| 4 | `990000000000000006` | Anucha Thongdee (~24) | **Temperature on demand** + BP card | fever → OPD |
| 5 | `990000000000000008` | ภูมิ รักเรียน (~6) | **Thai live call** (same pipeline, TH) | child → Pediatrics |

Runtime: ~12–18 minutes for all five.

> **Chat is the fallback, not the demo.** If the mic/room is unreliable on the
> day, every run below works identically by picking **Chat** instead of **Call**
> and typing / tapping the same inputs — but the voice-specific behaviour
> (endpointing, spoken summary, slip-after-speech timing) only shows on a **Call**.

---

## 0. Setup (once, before the demo)

1. **Databases (Docker):** from the repo root — `docker compose up -d`
   (Postgres :5432 + mock hospital DB :8001). Rebuild the HIS mock if the
   volume is stale: `docker compose up -d --build --force-recreate his-mock`.
2. **Prepare Postgres:** `cd hospital-hotline-assistant-api && uv run python
   scripts/init_db.py` (migrations + criteria + HIS health-check).
   If you only need to refresh criteria after a code pull:
   `uv run python scripts/seed_screening_criteria.py`.
3. **Backend:** `uv run uvicorn app.main:app --reload` → http://localhost:8000
4. **Frontend:** `cd hospital-hotline-assistant-web && npm run dev` →
   http://localhost:5173
5. **Voice must be enabled:** the web `.env` needs `VITE_ENABLE_VOICE=true`, and
   the backend needs Google STT/TTS credentials (ADC). Do a **10-second mic
   check** before the audience arrives — start a call on any visit, say
   "hello", confirm you see your words and hear a reply.
6. *(Optional)* In **Admin → 📋 Triage Manual**, upload the manual PDF so spoken
   explanations cite real manual phrasing. Decisions work without it.

### Reset between rehearsals

After a run, a visit is left `screened`/`routed`. To demo the same IDs again,
reset the mock hospital DB back to the blank "registered" state:

```bash
# from hospital-hotline-assistant-api/
uv run python scripts/reset_his.py                       # reset ALL visits
uv run python scripts/reset_his.py 990000000000000004    # reset just one/some
```

(It calls the mock's `POST /api/admin/reset`; uses `HIS_BASE_URL` /
`HIS_API_KEY` from your `.env`.) Recreating the container
(`docker compose up -d --force-recreate his-mock`) also gives a fresh blank DB.

**Two windows to have open on stage:**
- **Patient**: http://localhost:5173/patient
- **Staff**: http://localhost:5173/admin (super-admin `ops.admin@mfu.local`)
  — keep the **🏥 Hospital DB** tab visible; it's "the hospital side".
  Nurse confirmations: http://localhost:5173/nurse

---

## What changed in this booth build (PM feedback)

Memorize these four beats — they show up in almost every run:

### 1. No upfront vitals form

Landing → visit ID → **Call** or **Chat** starts immediately. There is no
`/vitals` gate. Age (and any HIS vitals already on the visit) come from the
linked visit; booth measurements are collected **mid-interview**.

### 2. When blood pressure is asked (and when it is not)

| Complaint category | BP asked? |
|---|---|
| chest pain, cough/dyspnea, abdominal pain, headache, fever, injury, pregnancy, generic | **Yes** — always (after red flags, before most history slots) |
| ear, nose/throat, eye, musculoskeletal, urinary, mental health | **Only if age ≥ 60** (or skip entirely if age unknown) |

The patient never hears that rule — they just see/hear the BP request when it applies.

### 3. The BP measurement card (two buttons)

When the engine asks for BP, a card appears under the transcript:

1. **Use the machine** — instruction to put the arm in the cuff and press START;
   the booth long-polls the Omron; values auto-fill; confirm.
2. **Enter manually** — type systolic / diastolic (/ pulse).

Submit feeds the reading into the next turn (e.g. spoken continuation
`BP 122/78`). Device provenance is `source: device` only when cuff values were
not edited.

Other measurement cards:

- **Temperature** — plain °C input (fever pathways only).
- **Weight & height** — one combined step near the **end** of every non-emergency
  interview (pre-disposition), before the department recommendation.

The **BP and weight/height cards have a "Skip this step" button** (cuff busy,
patient in a hurry) — the interview simply continues without the reading.
Temperature has no skip (it gates fever rules).

### 4. Quick-reply chips + free-text always available

Every question shows tappable options under the last assistant line.
**Tap wins over voice** mid-call; the composer / mic stays available.

- **Single-symptom red flags** → **Yes / No**.
- **Multi-symptom red flags** (e.g. fever's "confusion, trouble breathing, or
  stiff neck?", headache's stroke check) → **one chip per symptom + "None of
  these"** — a tap is always unambiguous. If the patient just says "yes" to
  one of these, the AI asks the same question **once more** with the chips
  (it will not guess which symptom they meant).
- **History questions** (onset/duration/character) → 3–4 **contextual chips
  generated with the question wording** (falling back to nurse-authored ones).
- **Pain/severity** → 0–10 chips.

Each patient answer is tagged **voice / typed / button** — visible in the
nurse portal's Conversation tab.

### 5. Follow-up note (non-emergency only)

After the department explanation (levels 3–5), the AI asks:

> Before you go — is there anything you'd like to ask or tell the doctor?
> I'll note it for them.

- **No** → closing line; flow complete.
- **Yes** → "What would you like the doctor to know?" → patient speaks/types;
  system **records + acknowledges** (never answers medically).
- Or they can speak/type the note directly on the first follow-up turn.

Emergencies (levels 1–2) **skip** follow-up and end immediately.

### 6. Slip in a new tab; map stays in-page

When the flow is complete, a **screening slip** opens in a **new tab**
(`/slip/<sessionId>`): slip code, visit ID, **patient name**, measured vitals,
recommended **department** only (never triage level/color). A **View your slip**
button stays on the page if the popup was blocked. The wayfinding **map**
remains on the chat/call page.

### 7. How routing is decided (what to say on stage)

The deterministic engine picks MOPH acuity + department from versioned criteria:

- **What they say** → findings + OLDCARTS slots (red flags first).
- **Measured vitals** → e.g. SBP > 180 can force Emergency even on a "mild" complaint.
- **Age from HIS** → under-15 → Pediatrics; age ≥ 60 can unlock BP on ENT-like complaints.
- **OPD-first** → non-emergency stays OPD; levels 1–2 force Emergency.
- Patients hear only the **department destination**; nurses see level, reasons,
  citations, and any **patient follow-up** note in `/nurse`.

---

## The booth flow, every run

Patient enters a **visit ID** → system greets them **by name** → **Call** or
**Chat** starts → AI interviews with **quick-reply chips** → asks for
**measurements in-conversation** when needed → recommends a **department** →
offers a **follow-up note** (non-emergency) → **slip** opens in a new tab
(map stays in-page) → call auto-ends. Staff see Stage-1 write-back; Stage-2
after nurse confirm.

**Speaking tips for the presenter:** speak a full sentence, then pause — the
call waits. One answer per turn. Prefer **tapping chips** when you want a clean,
predictable demo answer.

---

## Run 1 — Named greeting, chips, follow-up, slip tab → General OPD

**The point of this run:** walk the full new UX end-to-end on a routine adult —
and note what is **deliberately absent**: no BP request.

**Patient window** (`/patient`):
1. **Hospital visit ID** `990000000000000004` → pick **Call**.
2. Call auto-starts and greets: **"Hello Waraporn Srisuk, welcome…"**
3. Say: **"I have a sore throat and a mild cough for two days."**
   (Sore-throat-first lands on the **nose/throat pathway**.)
4. Answer red-flag / history questions. When chips appear (Yes/No, onset
   options, severity 0–10), **tap them** — point out that tap overrides voice
   and free-text is still there.
5. **No BP card appears — that's the feature**: ENT-like pathways skip BP for
   patients under 60 (triage research: BP doesn't change routing for minor
   ENT complaints). Contrast with Runs 2–4.
6. Near the end: **weight & height** card — e.g. **60 kg / 170 cm** (or tap
   **Skip this step**).
7. AI speaks the department recommendation (**OPD General Practice** / similar).
8. **Follow-up offer** — tap **No**, *or* tap **Yes** then say something like
   **"Please tell the doctor I am allergic to penicillin"** (system only notes it).
9. **Slip** opens in a **new tab** (name + vitals + department); **map** stays
   on the call page. Call auto-ends.

> **Talking point:** no blocking vitals form; BP is *not* asked because this
> pathway doesn't need it (evidence-based, age-gated); chips make answers
> booth-proof; follow-up is record-only; slip is for the desk, map is for
> wayfinding.

**Staff window** → **🏥 Hospital DB** → visit moves **registered → screened**
(vitals + follow-up text if any). **Nurse** (`/nurse`): search **slip code** →
open assessment → show **Patient follow-up** row if you left a note; open the
**Conversation** tab to show each answer tagged **voice / typed / button** →
**Confirm routing** → visit becomes **routed**.

---

## Run 2 — Routing by age (age from HIS) → Pediatrics

**The point of this run:** the decision uses age the patient never typed.

**Patient window** (`/patient`):
1. Visit ID `990000000000000003` → **Call**.
2. Greeting uses the HIS name (**น้ำใส ใจเย็น**).
3. Say: **"my son has a cough and a runny nose."**
4. Answer reassuringly via chips / voice (*no trouble breathing, no blood, no
   fever, mild, started a few days ago*).
5. When the **BP card** appears (cough pathway), enter a child-plausible reading
   e.g. **105 / 68**. Enter weight/height near the end (e.g. **22 kg / 118 cm**).
6. Decline follow-up (**No**).
7. **Result:** routes to **OPD Pediatrics**; slip opens in a new tab.

> **Talking point:** it never asked the child's age — it read **~8** from the
> hospital DB when the visit ID was linked, and the under-15 rule sent them to
> pediatrics. If the HIS hadn't known the age, *then* it would ask by voice.

**Staff window** → Hospital DB → **screened** → Nurse confirms → **routed**
(`second_location` = OPD Pediatrics).

---

## Run 3 — Routing by measured BP → EMERGENCY

**The point of this run:** the same "mild" style of complaint dispositions
differently because of a measured number — emergency banner mid-call.

**Patient window** (`/patient`):
1. Visit ID `990000000000000005` → **Call**.
2. Greeting: **ประเสริฐ สุขสม** (elderly — headache pathway always asks BP).
3. Say: **"I feel a bit dizzy and have a headache."**
4. The **stroke check** shows per-symptom chips (face drooping, weakness, slurred
   speech…) — tap **None of these**. Answer the remaining red flags calmly
   (**No** to the worst-headache-of-life question — a Yes there ends the run
   at Emergency before BP is ever measured).
5. When the **BP card** appears, enter **200 / 122** (manual is fine for stage).
   That number is the star of the demo.
6. **Result:** AI routes to the **Emergency Department** — emergency banner;
   speaks ER guidance. **Follow-up is skipped** for emergencies. Slip opens in
   a new tab (department = Emergency; no level shown on the slip). Weight/height
   is **not** asked — emergencies dispose immediately.

> **Talking point:** a routine headache would stay OPD, but **SBP 200** trips
> the danger-vitals rule. Decisions use measured vitals, not just words. No
> follow-up ask on emergencies — get them to ER.

**Staff window** → Hospital DB → **screened** with pressure `200/122`. Confirm
in Nurse portal for Stage 2.

---

## Run 4 — Temperature on demand + BP card → OPD

**The point of this run:** temperature isn't collected for everyone — mid-call,
only when a fever pathway needs it. BP still appears on the fever pathway.

**Patient window** (`/patient`):
1. Visit ID `990000000000000006` → **Call**.
2. Greeting: **Anucha Thongdee**.
3. Say: **"I have a fever and a cough."**
4. The fever **danger question** ("confusion, trouble breathing, or stiff
   neck?") shows **one chip per symptom + "None of these"** — tap **None of
   these**. (Tapping a symptom chip like *Stiff neck with fever* would end the
   run at **Emergency** — a good ad-lib if you want a second escalation demo.)
   Answer the remaining red flags with the **No** chips.
5. AI asks for **temperature** → numeric card → enter **38.5** → Submit
   (continuation turn; no need to speak the number).
6. **BP card** appears (fever pathway) → enter e.g. **118 / 76** — or tap
   **Skip this step** to show that measurements never block the flow.
7. **Weight & height card** near the end (every non-emergency run ends with it)
   → e.g. **60 kg / 170 cm** → finish interview → department recommendation.
8. Follow-up: tap **No** (or leave a short note).
9. Slip opens in a new tab.

> **Talking point:** temperature is *conditional*; BP on fever/cough pathways
> is expected; weight/height is always last before disposition for non-emergencies.

**Staff window** → Hospital DB → **screened** (vitals include temperature) →
Nurse confirms → **routed**.

---

## Run 5 — Thai live call → Pediatrics

**The point of this run:** full Thai voice experience — same pipeline, bilingual
chips / cards / follow-up / slip.

**Patient window** (`/patient`):
1. Switch the language toggle to **ไทย (TH)**.
2. Visit ID `990000000000000008` → **โทร (Call)**.
3. Thai greeting with HIS name (**ภูมิ รักเรียน**).
4. Say: **"ลูกสาวมีอาการไอและเจ็บคอ"** ("my daughter has a cough and a sore throat").
5. Answer Thai questions; tap Thai **ใช่ / ไม่** chips when shown.
6. When BP / weight-height cards appear, enter values (same UX, Thai labels).
7. Follow-up offer in Thai → tap **ไม่**.
8. **Result:** speaks routing — **OPD กุมารเวชกรรม (Pediatrics)** — slip opens
   in a new tab (Thai UI strings).

> **Talking point:** identical pipeline, criteria, and write-back as English —
> Thai STT/TTS and nurse-approved Thai wording throughout. Patient still never
> hears a triage level.

**Staff window** → Hospital DB → **screened** → Nurse confirms → **routed**.

---

## Optional talking points (if asked)

**"Why didn't ENT ask for BP?"**  
Ear / nose-throat / eye / MSK / urinary / mental-health pathways skip BP unless
the patient is **≥ 60**. Run 1 shows exactly this (sore throat, 33 → no BP
card); contrast with Run 2 (child cough — BP asked) and Run 3 (headache /
elderly). Same sore throat on visit `…005` (age 78) **would** ask BP — the
age guard.

**"What if the patient answers 'yes' to a multi-symptom question?"**  
The AI never guesses which symptom they meant — it asks once more showing one
chip per symptom plus **None of these**. Tapping a symptom chip (or naming it)
records exactly that finding; a red-flag symptom escalates immediately.

**"Does the AI answer medical questions in follow-up?"**  
No — it only **records** the patient's words for the doctor and acknowledges.
Anything clinical stays for the clinician.

**"What's on the slip vs the nurse screen?"**  
Slip (patient): code, visit ID, name, vitals, **department**.  
Nurse: full acuity/reasons/citations + patient follow-up + confirm/reroute.

---

## What the five runs demonstrate (the pitch)

- **Named, hands-free booth flow** — greet by HIS name; patient-paced turns;
  chips + measurement cards mid-call.
- **Decisions from three inputs** — what they **say**, **measured vitals**
  (Run 3), and **age** (Run 2), against nurse-approved criteria.
- **Vitals in-flow, not a gate** — BP complaint/age-gated with machine-vs-manual
  buttons (and a skip); temperature only when fever needs it; weight/height last.
- **Follow-up is safe** — record + acknowledge for the doctor; skipped on
  emergencies.
- **Slip + map** — slip in a new tab for the desk; map stays for wayfinding.
- **Reads from / writes to the hospital** — age in from HIS; Stage-1 push after
  disposition; Stage-2 only after a **nurse signs off**.
- **Deterministic + safe** — patient never hears a triage level; every decision
  has a reason a nurse can read.

## If something looks off

- **No sound / mic not captured** → check `VITE_ENABLE_VOICE=true` and Google
  STT/TTS credentials (Setup step 5); redo the 10-second mic check. As a last
  resort, run the scenario in **Chat** (type / tap the same inputs).
- **It cuts you off / says "couldn't hear" too eagerly** → speak a full sentence,
  then pause; or just **tap a chip**.
- **BP card never appears** → expected on ENT-like pathways if age &lt; 60
  (that IS Run 1's talking point); use a cough/fever/headache complaint
  (Runs 2, 3, 4) to show the card.
- **It repeats a red-flag question after you say "yes"** → expected: a bare yes
  to a multi-symptom question can't be mapped; tap one of the symptom chips or
  **None of these**.
- **Cuff busy / no cuff on stage** → tap **Skip this step** on the BP card (or
  **Enter manually**); the interview continues without the reading.
- **Slip didn't pop** → popup blocker; use **View your slip** on the page.
- **Visit already shows *screened/routed*** → reset it: `uv run python
  scripts/reset_his.py <visit_id>` (Setup → Reset).
- **Interview asks for age** → the visit wasn't linked; re-enter the visit ID.
- **Greeting has no name** → HIS mock not rebuilt / visit missing `patient_name`;
  recreate his-mock and re-seed (Setup steps 1–2).
- **Explanation is a plain template** (not manual-flavoured) → Triage Manual
  isn't indexed; upload it (Setup step 6). Decisions are unaffected.
- **Criteria missing BP / weight questions** → reseed:
  `uv run python scripts/seed_screening_criteria.py`.
