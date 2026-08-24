# Demo test plan (English) — five patients, expected criteria and routing

The English-language twin of `docs/demo-test-plan.md`: the same five decision
paths, with the patient speaking **English** at the kiosk (language toggle →
EN). The rules are language-independent, so the expected level, department
and rule are identical; what changes is the script and the question
wording. All five were run live on 2026-08-22 (criteria v5 with natural wording,
Gemini, RAG on, `evals/reports/2026-08-22T184028Z.md`) and passed; the scripts below are the
harness's own (`evals/vignettes.json`, ids in each heading), and the question
order shown is the one the engine actually produced.

## Before you start

- Stack up: Docker (Postgres + mock HIS), backend `:8000`, web `:5173`; admin
  Rule Book shows **v5**.
- Seeded HNs (`hospital-his-mock/sample_patients.csv`): 09900001 สมชาย ใจดี
  (male, 41), 09900002 สมหญิง รักษาดี (female, 68). The kiosk starts a fresh
  session for the same HN each time.
- Switch the kiosk to **English** before the greeting; STT/TTS follow
  (`en-US`). Device cards (cuff, thermometer, oximeter) pop when the engine
  asks; without a device at hand, type the value and say so.
- Nurse portal in a second window, logged in as `opd.nurse@mfu.local`.
- HIS-recorded gender skips the gender question; for a walk-in without one the
  engine asks once and "skip" is a valid answer.

## What "pass" means, for every scenario

| Check | Where you see it |
|---|---|
| Level is the expected MOPH level | nurse review header (the patient never hears it) |
| Department = expected, and the patient *heard its name* | kiosk transcript + nurse review |
| The listed rule appears under reasons, with its citation | nurse review → reasons |
| Must-ask question was asked — it names the symptom (the wording may vary; the template is the fallback) | kiosk transcript |
| Must-not-ask question did not appear | kiosk transcript |
| No level / colour / diagnosis in anything the patient heard | kiosk transcript |
| Vitals show a device / typed tag | nurse review vitals tiles |

---

## 1 · Chest pain — emergency from words alone (`cp_en_crushing`)

**Patient, สมชาย 09900001:**
“I've got this crushing pressure in my chest, like someone's sitting on it. It started about half an hour ago and I'm sweating buckets.”
→ *“Are you feeling that tightness in your chest right now?”* (a rewording — it must name chest pain) → “yes, that's right”
→ *“Are you sweating heavily or feeling a cold sweat right now?”* → “yes, that's right”.

**Expected:** 3 turns, no vitals asked.
- Level **2** — rule `tt_chest_pain_diaphoresis` *Chest pain with sweating (suspected ACS)*, MOPH 5-level / ESI decision point B. Adding “it goes up into my jaw and down my left arm” also fires `ft_mi_chest_pain` (heart-attack fast track).
- Department **the Emergency Department**; the reply says go now, staff notified.
- Shows: **confirm-before-fire** — both findings came from free speech, so the engine confirms each (naturally worded, symptom named) before declaring an emergency.
- Variation (corrections): open with “My stomach hurts” instead, answer the age question, then say “sorry, I got that wrong — it's not my stomach, it's a crushing pressure in my chest and I'm sweating” → the interview switches to the chest screen, the emergency reply names chest pain, and the nurse review lists *stomach* under the corrected-complaint history, not as the chief complaint.

## 2 · Breathlessness — emergency from the oximeter (`ws_en_dyspnea_spo2_88`)

**Patient, 09900002:** “I can't seem to get enough air, I get breathless walking. Two days now.”
→ *“Right now, are you having any trouble breathing?”* → “yes, it's hard to breathe”
→ gender → “skip” (fine)
→ *“Since you mentioned breathing difficulty, please put your finger in the pulse oximeter at the booth so I can check your oxygen level.”* → **oximeter card** → clip the finger / type **88**.

**Expected:** 4 turns.
- Must ask `uq_spo2` — gated on confirmed breathlessness; the fever patient in scenario 4 never gets it.
- Level **1** — rule `l1_adult_spo2_low` *SpO₂ < 90 % with breathing difficulty*, MFU Level 1 “O₂ sat < 90 % ยกเว้น COPD”.
- Department **the Emergency Department**. Nurse tiles: SpO₂ 88 with a device (or typed) tag.
- Variation: type **92** → the engine asks the retraction question (`dc_retraction`: *“When you breathe in, do the spaces between your ribs or at the base of your neck pull inward?”*); “yes” → level **2** (`dv_adult_spo2_90_94`); “no” → the interview continues.

## 3 · Abdominal pain — a spoken pain score fires a level-2 rule (`ap_en_rlq`)

**Patient, any HN:** “My stomach's been hurting since yesterday. It started around my belly button but now it's down on the lower right, and it really hurts when I walk.”
→ breathing “breathing is fine” → gender → *“Have you vomited blood, or had bloody or black stools in the past week?”* → “no blood anywhere, no”
→ *“On a scale of 0 to 10, how severe is the pain?”* → “it's like a 7”
→ *“Are you feeling any belly pain at this moment?”* (confirm) → “yes, that's right”.

**Expected:** 6 turns.
- Level **2** — `surg_severe_pain_critical_site` *Severe pain (≥ 7) at head/neck, chest or abdomen*, MFU Triage Level 2 ศัลยกรรม “Pain score ≥ 7 อวัยวะสำคัญ”.
- Department **the Emergency Department**. Say “about a 4” instead → routine path → **OPD Internal Medicine** (the abdominal-pain routing table sends general abdominal pain to medicine; surgery is reserved for a mass, anal symptoms or GI bleeding).
- Shows: a **number** the patient said became a vital (`pain_score`) and drove a rule.
- Variation (corrections): say “7”, and when the confirm question comes answer “sorry, I meant 4, it's more of a dull ache” → the level-2 path drops, the nurse summary shows severity 4, the interview continues to OPD Internal Medicine.

## 4 · Fever — routine, and the safety screen must NOT fire (`ws_en_fever_no_spo2`)

**Patient, 09900001:** “Fever and body aches for two days.”
→ breathing “breathing is normal” → gender
→ *“Any confusion, trouble breathing, or stiff neck with the fever?”* → “no”
→ *“Are you currently receiving chemotherapy?”* → “no”
→ *“Do you have any rash or blisters, especially on palms, soles, or around the mouth?”* → “no”
→ **thermometer card** (38.4) → **cuff card** (normal)
→ associated symptoms “no” → weight/height → explanation → follow-up offer “no, that's all, thank you”.

**Expected:** ~11 turns.
- Level **4**, department **OPD General Practice** (`opd_general`) — routing table `fever → opd_general`.
- Must ask `fv_danger` and `fv_chemo` — the two level-2 gates for fever (`tt_fever_chemo`).
- **Must NOT ask** `uq_spo2` (no breathlessness) and **must NOT ask** `mh_suicide`.
- Nurse review shows the manual citation on the explanation (RAG on) and device tags on temp/BP.
- Shows: every question is worded naturally by the model — but each still names the symptom the manual's question names (the guard refuses any rewording that drops one); measurement requests stay fixed.

## 5 · Stress — the safety screen MUST fire, routes to psychiatry (`ws_en_stress_asks_selfharm`)

**Patient, 09900002:** “I've been really stressed and can't sleep for weeks, crying a lot.”
→ breathing “normal” → gender
→ **`mh_suicide`** *“Have you had thoughts of hurting yourself or ending your life?”* → “no, never thought about that”
→ thermometer / cuff cards → onset “about a month” → duration “five or six weeks”
→ *“Do you ever see or hear things that others don't, or feel like someone might be trying to hurt you?”* → “no”
→ weight/height → explanation.

**Expected:** ~10 turns.
- Must ask `mh_suicide` as the **first** template question — wording may vary, it must ask about hurting yourself / ending your life.
- Level **4**, department **OPD Psychiatry** (`opd_psychiatry`) — routing table `mental_health → opd_psychiatry`.
- Variation: answer “sometimes, yes, I do think about it” → level **2**, Emergency, staff notified — rule `psych_code_purple` *Risk of self-harm (Code Purple)*; disposes on the direct answer.

---

## After the five: the write-back

Pick scenario 4 or 5 in the nurse portal → approve → the publish dialog shows
the SBAR preview; the VN field is pre-filled from HIS (`current_visit`) or left
for the nurse → publish → *Mock HIS (demo only)* → `GET /api/visits` (Postman)
or the admin Database tab shows `second_location` set and `mfu_prescreen`
stored. Re-publish the same review → same queue number (idempotent).

## Known limits to state out loud

- Expected levels are the manual as *we* encoded it; not yet nurse-validated. The review step is where the nurse overrides, and every override is a candidate criteria edit.
- Speech recognition is Google today (`en-US`); a mis-heard word changes findings. Repeat the utterance if the transcript shows it wrong — the engine reacts to the transcript, not the audio.
- Gemini today, local model later: same prompts, same bodies (Postman *AI Model (local inference)*).
- After the disposition the level does not change from the booth: anything the patient adds (“wait, I got that wrong…”) is kept in the nurse's follow-up note, and the nurse decides. A device reading is never overridden by speech.
