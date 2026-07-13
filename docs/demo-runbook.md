# Demo Runbook — AI OPD Pre-Screening (booth flow, **live call first**)

Five short patient runs, all on the **live voice call** — the primary path.
The patient enters a hospital visit ID, our booth reads their age from the
hospital DB and collects vitals, then the AI **talks** the patient through
screening one question at a time (never showing a triage level). The decision
follows nurse-approved criteria — driven by what they **say**, their **measured
vitals**, and their **age** — and writes back to the hospital DB in two stages,
the second only after a nurse confirms.

The five runs are chosen so each isolates one idea:

| # | Visit ID | Shows | Outcome |
|---|---|---|---|
| 1 | `990000000000000004` | **Vitals asked + hands-free call** (endpointing, slip timing) | routine → General OPD |
| 2 | `990000000000000003` | **Routing by age** (age auto from HIS) | child → Pediatrics |
| 3 | `990000000000000005` | **Routing by vitals** (measured BP) | elderly → **Emergency** |
| 4 | `990000000000000006` | **Temperature on demand** (voice fever popup) | fever → OPD |
| 5 | `990000000000000008` | **Thai live call** (same pipeline, TH) | child → Pediatrics |

Runtime: ~12–15 minutes for all five.

> **Chat is the fallback, not the demo.** If the mic/room is unreliable on the
> day, every run below works identically by picking **Chat** instead of **Call**
> and typing the same inputs — but the voice-specific behaviour (endpointing,
> the spoken summary, the slip-after-speech timing) only shows on a **Call**.

---

## 0. Setup (once, before the demo)

1. **Databases (Docker):** from the repo root — `docker compose up -d`
   (Postgres :5432 + mock hospital DB :8001).
2. **Prepare Postgres:** `cd hospital-hotline-assistant-api && uv run python
   scripts/init_db.py` (migrations + criteria + HIS health-check).
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
(`cd hospital-his-mock && docker compose up -d --force-recreate`) also gives a
fresh blank DB.

**Two windows to have open on stage:**
- **Patient**: http://localhost:5173/patient
- **Staff**: http://localhost:5173/admin (super-admin `ops.admin@mfu.local`)
  — keep the **🏥 Hospital DB** tab visible; it's "the hospital side".

### The booth flow, every run

Patient enters a **visit ID** → the system fetches age + any HIS vitals →
**vitals screen** (required form) → **Call** → the call auto-starts and greets →
the AI interviews **by voice** → it **speaks** the routing, then the **slip**
appears (only after it stops talking) and the call auto-ends. Staff see the
write-back.

**Speaking tips for the presenter:** speak a full sentence, then pause — the
call waits (it won't cut you off, and won't say "sorry, I couldn't hear you" on
a first quiet moment). One answer per turn.

---

## Run 1 — Vitals asked + hands-free call → routine General OPD

**The point of this run:** show the vitals gate **and** the live-call basics —
patient-paced turns and the slip that waits for the AI to finish speaking.

**Patient window** (`/patient`):
1. **Hospital visit ID** `990000000000000004` → pick **Call**.
2. On the **vitals screen** — a **required form**, *Continue stays disabled
   until every field is filled*:
   - **Blood pressure**: tap **Measure with cuff** (Omron over Bluetooth) **or**
     type it — e.g. **122 / 78**.
   - **Pulse 74**, **Weight 60**, **Height 170** → **Continue**.
   - *(Temperature is deliberately NOT here — see Run 4.)*
3. The call **auto-starts and greets**. Say: **"I have a sore throat and a mild
   cough for two days."** Pause naturally between answers — it waits for you.
4. Answer its spoken questions reassuringly (no trouble breathing, no high
   fever, mild).
5. **Result:** it **speaks** the routing — **OPD General Practice** — and only
   **after it finishes talking** does the assessment **slip** appear; then the
   call auto-ends.

> **Talking point:** vitals are captured once, upfront, and mandatory — no skip.
> The call is hands-free by design (longer silence window, room-noise gate, no
> false "didn't hear you"), and the slip is held back until the spoken summary
> ends so it never pops up over the AI's voice.

**Staff window** → **🏥 Hospital DB** → **registered → screened**: measurements +
booth filled; complaint/reason/department still blank (Stage 2 waits for the
nurse). **Nurse** (`/nurse`): search the **slip code** → open → **Confirm
routing** → the visit becomes **routed**.

---

## Run 2 — Routing by age (age comes from the hospital DB) → Pediatrics

**The point of this run:** the decision uses age the patient never gave.

**Patient window** (`/patient`):
1. Visit ID `990000000000000003` → **Call**.
2. Vitals: BP **105 / 68** (typed or cuff), pulse **96**, weight **22**,
   height **118** → **Continue**.
3. When the call greets you, say: **"my son has a cough and a runny nose."**
4. Answer naturally — all reassuring (*no trouble breathing, no blood, no
   fever, mild, started 3 days ago*).
5. **Result:** it routes to **OPD Pediatrics** and shows the slip.

> **Talking point:** it never asked the child's age — it read **8** from the
> hospital DB the instant the visit ID was entered, and the under-15 rule sent
> it to pediatrics. If the HIS hadn't known the age, *then* it would ask by
> voice.

**Staff window** → Hospital DB → **screened** → Nurse confirms → **routed**
(`second_location` = OPD Pediatrics).

---

## Run 3 — Routing by vitals (measured BP drives it) → EMERGENCY

**The point of this run:** the same kind of mild complaint dispositions
differently because of a measured number — and the emergency banner fires
**mid-call**.

**Patient window** (`/patient`):
1. Visit ID `990000000000000005` → **Call**.
2. Vitals: **BP 200 / 122**, pulse **88**, weight **68**, height **165** →
   **Continue**. *(The BP is the star of the demo — a real measured value.)*
3. When it greets you, say: **"I feel a bit dizzy and have a headache."**
4. **Result:** the AI **immediately** routes to the **Emergency Department** —
   no interview loop — an emergency banner shows and it speaks the ER
   instruction.

> **Talking point:** a normal headache would be routine, but the **cuff reading
> of 200/122 drove the decision** — the deterministic rules caught the
> hypertensive crisis (`SBP > 180`) on turn 1, *before* any questions. The
> patient's measurements are part of the assessment, not just their words.

**Staff window** → Hospital DB → **screened** with `pressure 200/122`. (Confirm
in the Nurse portal to complete Stage 2.)

---

## Run 4 — Temperature on demand (voice fever popup) → OPD

**The point of this run:** temperature isn't collected for everyone — mid-call,
the engine **asks for it by voice** only when a fever pathway needs the number,
and a numeric popup takes the reading without breaking the hands-free flow.

**Patient window** (`/patient`):
1. Visit ID `990000000000000006` → **Call**.
2. Vitals: BP **118 / 76**, pulse **82**, weight **64**, height **168** →
   **Continue**. *(Still no temperature here.)*
3. When it greets you, say: **"I have a fever and a cough."**
4. Answer the fever red-flags out loud (no confusion, no trouble breathing, no
   stiff neck) and confirm the **fever is present**.
5. The AI **speaks** the temperature request, and when it finishes, a **numeric
   temperature popup** appears. Enter **38.5** → **Submit** — the call
   **continues on its own** (no need to speak the number).
6. **Result:** it folds 38.5 °C into the assessment, finishes the interview by
   voice, and routes (e.g. **General OPD**).

> **Talking point:** BP / pulse / weight / height are captured once upfront;
> temperature is *conditional* — requested only when a fever rule is in play.
> The popup fires **after** the AI finishes speaking the request, and on submit
> the reading is fed straight back into the call so it proceeds hands-free.

**Staff window** → Hospital DB → **screened** (vitals include the temperature)
→ Nurse confirms → **routed**.

---

## Run 5 — Thai live call (same pipeline, in Thai) → Pediatrics

**The point of this run:** the whole voice experience in Thai — one build, both
languages, verbatim nurse-approved wording.

**Patient window** (`/patient`):
1. Switch the language toggle to **ไทย (TH)**.
2. Visit ID `990000000000000008` → **โทร (Call)**.
3. Vitals: BP **100 / 64**, pulse **100**, weight **20**, height **112** →
   **ดำเนินการต่อ (Continue)**.
4. When it greets you in Thai, say (in Thai): **"ลูกสาวมีอาการไอและเจ็บคอ"**
   ("my daughter has a cough and a sore throat"). Answer its Thai questions
   reassuringly.
5. **Result:** it speaks the routing in Thai — **OPD กุมารเวชกรรม (Pediatrics)**
   — and the slip appears after it finishes speaking.

> **Talking point:** identical pipeline, criteria, and write-back as the English
> runs — Thai STT/TTS and Thai verbatim question wording throughout. The patient
> still never hears a triage level.

**Staff window** → Hospital DB → **screened** → Nurse confirms → **routed**.

---

## What the five runs demonstrate (the pitch)

- **Live, hands-free voice first** — patient-paced turns (Run 1), an emergency
  spoken mid-call (Run 3), a mid-call measurement popup (Run 4), and full Thai
  (Run 5).
- **Decisions from three inputs** — what they **say**, their **measured vitals**
  (Run 3), and their **age** (Run 2), all against nurse-approved criteria.
- **Vitals are first-class** — mandatory upfront (Run 1); temperature only when
  a rule needs it (Run 4).
- **Reads from the hospital, writes back to it** — age in from the HIS; results
  out in two stages, the routing only after a **nurse signs off**.
- **Deterministic + safe** — the patient never hears a triage level; every
  decision has a reason a nurse can read.

## If something looks off

- **No sound / mic not captured** → check `VITE_ENABLE_VOICE=true` and Google
  STT/TTS credentials (Setup step 5); redo the 10-second mic check. As a last
  resort, run the scenario in **Chat** (type the same inputs).
- **It cuts you off / says "couldn't hear" too eagerly** → confirm you're on the
  current build; the endpointing was tuned for the booth (longer silence
  window, higher noise gate). Speak a full sentence, then pause.
- **Slip pops up while it's still talking** → old build; the current one holds
  the slip until the spoken summary drains.
- **Visit already shows *screened/routed*** → reset it: `uv run python
  scripts/reset_his.py <visit_id>` (Setup → Reset).
- **Interview asks for age** → the visit wasn't linked; re-enter the visit ID.
- **Explanation is a plain template** (not manual-flavoured) → the Triage Manual
  isn't indexed; upload it (Setup step 5). Decisions are unaffected.
