# Demo Runbook — AI OPD Pre-Screening (booth flow)

Three short patient runs that show the whole story: the patient enters a
hospital visit ID, our booth reads their age from the hospital DB, measures
vitals, the AI screens them one question at a time (never showing a triage
level), routes them to a department, and writes the result back to the
hospital DB in two stages — the second only after a nurse confirms.

Runtime: ~8–10 minutes for all three.

---

## 0. Setup (once, before the demo)

1. **Databases (Docker):** from the repo root — `docker compose up -d`
   (Postgres :5432 + mock hospital DB :8001).
   - For a clean before/after story, reset the mock so every visit starts
     blank: `cd hospital-his-mock && docker compose down && docker compose up -d`.
2. **Prepare Postgres:** `cd hospital-hotline-assistant-api && uv run python
   scripts/init_db.py` (migrations + criteria + HIS health-check).
3. **Backend:** `uv run uvicorn app.main:app --reload` → http://localhost:8000
4. **Frontend:** `cd hospital-hotline-assistant-web && npm run dev` →
   http://localhost:5173
5. *(Optional)* In **Admin → 📋 Triage Manual**, upload the manual PDF so
   explanations cite real manual phrasing. Decisions work without it.

**Two windows to have open on stage:**
- **Patient**: http://localhost:5173/patient
- **Staff**: http://localhost:5173/admin (super-admin `ops.admin@mfu.local`)
  — keep the **🏥 Hospital DB** tab visible; it's "the hospital side".

The three demo visit IDs (all pre-loaded, blank, in the mock hospital DB):

| Visit ID | Patient | Demo point |
|---|---|---|
| `990000000000000003` | child, ~8 yrs | routine → pediatrics; age auto-fills |
| `990000000000000005` | elderly, ~78 yrs | **emergency from the measured BP** |
| `990000000000000004` | adult, ~33 yrs | routine → general OPD |

---

## Run 1 — Child with a cough (routine; age comes from the hospital DB)

**Patient window** (`/patient`):
1. In **Hospital visit ID**, type `990000000000000003`.
2. Pick **Chat**.
3. On the vitals screen: measure BP with the cuff (or enter **105 / 68**),
   and optionally weight **22**, height **118**, temp **37.0** → Continue.
4. Type: **"my son has a cough and a runny nose"**.
5. Answer the AI's questions naturally — all reassuring, e.g. *no trouble
   breathing, no blood, no fever, mild, started 3 days ago*.
6. **Result:** the AI guides you to **OPD Pediatrics** and prints a slip with
   a code like `MCH-XXXX-XXXX`. Note it never mentioned a triage "level".

> **Talking point:** it never asked the child's age — it read **8** from the
> hospital DB the moment the visit ID was entered, which is also why it routed
> to pediatrics (under-15 rule).

**Staff window** → **🏥 Hospital DB** tab → click the visit:
- It went **registered → screened**. The **measurements + booth** are now
  filled by our system. The **complaint / reason / department are still
  blank** — those wait for the nurse (Stage 2).

**Nurse step** (`/nurse`): search the **slip code** from the patient's slip →
open the case → **Confirm routing**. Refresh the Hospital DB tab → the visit is
now **routed**: `second_location` = OPD Pediatrics, and the complaint/reason
are published.

---

## Run 2 — Elderly patient, EMERGENCY from the measured blood pressure

**Patient window** (`/patient`):
1. Visit ID `990000000000000005` → **Chat**.
2. Vitals: enter **BP 200 / 122**, temp 36.8 → Continue. *(This is the star of
   the demo — a real measured value.)*
3. Type: **"I feel a bit dizzy and have a headache"**.
4. **Result:** the AI **immediately** tells the patient to go to the
   **Emergency Department** — no interview loop — and an emergency banner shows.

> **Talking point:** same kind of mild complaint as a normal headache, but the
> **cuff reading of 200/122 drove the decision** — the deterministic rules
> caught the hypertensive crisis (`SBP > 180`) on turn 1. The patient's own
> measurements are part of the assessment, not just what they say.

**Staff window** → Hospital DB → the visit is **screened** with `pressure
200/122`. (Confirm it in the Nurse portal the same way to complete Stage 2.)

---

## Run 3 — Adult with a sore throat (routine → general OPD)

**Patient window** (`/patient`):
1. Visit ID `990000000000000004` → **Chat**.
2. Vitals: **BP 122 / 78**, temp 36.7 → Continue.
3. Type: **"I have a sore throat and a mild cough for two days"**.
4. Answer reassuringly (no breathing trouble, no fever, mild).
5. **Result:** routed to **OPD General Practice** — the reason notes it
   screened at general OPD first (didn't meet a specialty's criteria).

> **Talking point:** one question at a time, systematic, and it lands on
> general OPD — the OPD-first policy the nurses asked for, with the reasoning
> visible to staff but the level hidden from the patient.

**Staff window** → Hospital DB → **screened** → Nurse confirms → **routed**.

---

## What each run demonstrates (the pitch)

- **Reads from the hospital, writes back to it** — age in from the HIS; results
  out in two stages, the routing only after a **nurse signs off** (human in the
  loop).
- **Measurements matter** — the same complaint routes differently by BP.
- **Deterministic + safe** — decisions come from the nurse-approved criteria,
  not free-form AI; the patient never sees a triage level; every decision has a
  reason a nurse can read.
- **Bilingual** — rerun any scenario with the **TH** toggle; identical flow,
  Thai throughout.

## If something looks off

- Visit already shows *screened/routed* → reset the mock (Setup step 1) so it's
  blank again.
- Interview asks for age → the visit wasn't linked; re-enter the visit ID at
  the start.
- Explanation is a plain template (not manual-flavoured) → the Triage Manual
  isn't indexed; upload it (Setup step 5). Decisions are unaffected.
