# Demo test plan — five patients, expected criteria and routing

Five scripted patients that together exercise every decision path of the
engine: a red flag from words alone, a red flag from a **device**, a pain-score
rule, a routine OPD case that must *not* trigger a safety screen, and a
mental-health case that *must*. Each one names the criteria rule that should
fire (as shown in the nurse review's "เหตุผล / reasons" with its manual
citation), the department the patient should hear, and what to check on
screen. All five were run live against the engine on 2026-08-21
(`evals/reports/2026-08-21T111203Z.md`, criteria v3, Gemini, RAG on) and
again on 2026-08-22 after the corrections and natural-wording work
(`2026-08-22T184028Z.md`, criteria v5) and passed both times; the scripts below are the same ones the
harness used (`evals/vignettes.json`, ids in each heading). The "Variation
(corrections)" lines show the patient changing their story mid-interview —
see `docs/screening-flow-walkthrough.md` for what happens under the hood.

## Before you start

- Stack up: Docker (Postgres + mock HIS), backend `:8000`, web `:5173`; admin
  Rule Book shows **v5**.
- Use seeded HNs (`hospital-his-mock/sample_patients.csv`): 09900001 สมชาย ใจดี
  (male, 41), 09900002 สมหญิง รักษาดี (female, 68), 09900005/09900007 (used yesterday; fine to reuse).
  A fresh session per demo: the kiosk starts a new session for the same HN.
- Devices: the cuff, thermometer and oximeter cards appear when the engine asks;
  if a device is not at hand, the card accepts a typed value — say so in the demo.
- Nurse portal open in a second window, logged in as `opd.nurse@mfu.local`.

## What "pass" means, for every scenario

| Check | Where you see it |
|---|---|
| Level is the expected MOPH level | nurse review header (patient never hears it) |
| Department = expected, and the patient *heard its name* | kiosk transcript + nurse review |
| The listed rule appears under reasons, with its citation | nurse review → เหตุผล |
| Must-ask question was asked — it names the symptom (the wording may vary; the template is the fallback) | kiosk transcript |
| Must-not-ask question did not appear | kiosk transcript |
| No level / colour / diagnosis in anything the patient heard | kiosk transcript |
| Vitals show a device / typed tag | nurse review vitals tiles |

---

## 1 · Chest pain — emergency from words alone (`cp_th_crushing`)

**Patient (th), สมชาย 09900001:**
“แน่นหน้าอกเหมือนช้างเหยียบเลยค่ะ เป็นมาสักครึ่งชั่วโมงแล้ว เหงื่อแตกท่วมตัว”
→ engine confirms (“ตอนนี้ยังเจ็บหรือแน่นหน้าอกอยู่ไหมคะ” or a rewording naming chest pain) → “ใช่ค่ะ” → confirms sweating → “ใช่ค่ะ”.

**Expected:** 2–3 turns, no vitals asked.
- Level **2** — rule `tt_chest_pain_diaphoresis` *Chest pain with sweating (suspected ACS)*, MOPH 5-level / ESI decision point B. If the patient also says “ร้าวไปกราม/แขนซ้าย”: `ft_mi_chest_pain` heart-attack fast track.
- Department **ห้องฉุกเฉิน (emergency)**; the reply says go now, staff notified.
- Shows: **confirm-before-fire** — the red flag came from free speech, so the engine asks once before declaring an emergency; never from an inferred word.
- Variation (corrections): open with “ปวดท้องค่ะ” instead, answer age, then say “เอ่อ พูดผิดค่ะ ไม่ได้ปวดท้อง แต่แน่นหน้าอก เหงื่อแตก” — the interview switches to the chest screen, the emergency reply names chest pain, and the nurse review shows ปวดท้อง under the corrected-complaint history, not as the chief complaint.

## 2 · Breathlessness — emergency from the oximeter (`ws_th_dyspnea_spo2_88`)

**Patient (th), 09900002:** “หายใจไม่อิ่มค่ะ เหนื่อยเวลาเดิน มาสองวันแล้ว” → “หายใจลำบากค่ะ” → gender “ไม่มีค่ะ” (declines; fine) → **oximeter card appears** → clip the finger / type **88**.

**Expected:** 4 turns.
- Must ask `uq_spo2` (“…รบกวนวางนิ้วบนเครื่องวัดออกซิเจนปลายนิ้ว…”) — the SpO₂ request is gated on confirmed breathlessness; a fever patient never gets it (scenario 4).
- Level **1** — rule `l1_adult_spo2_low` *SpO₂ < 90 % with breathing difficulty*, MFU Level 1 “O₂ sat < 90 % ยกเว้น COPD”.
- Department **ห้องฉุกเฉิน**. Nurse tiles: SpO₂ 88 with a **device** tag (or “typed”).
- Variation for the audience: type **92** instead → engine asks the retraction question (`dc_retraction`); “ใช่” → level **2** (`dv_adult_spo2_90_94`); “ไม่” → continues the interview.

## 3 · Abdominal pain — a pain score the patient said fires a level-2 rule (`ap_en_rlq`)

**Patient (en), any HN:** “My stomach's been hurting since yesterday. It started around my belly button but now it's down on the lower right, and it really hurts when I walk.” → breathing “fine” → gender → GI bleed “no blood anywhere” → pain “it's like a 7” → confirm “yes, that's right”.

**Expected:** 6 turns.
- Level **2** — `surg_severe_pain_critical_site` *Severe pain (≥ 7) at head/neck, chest or abdomen*, MFU Triage Level 2 ศัลยกรรม “Pain score ≥ 7 อวัยวะสำคัญ”.
- Department **Emergency**. (Say “4” instead of “7” → routine path → **OPD Internal Medicine**: the abdominal-pain routing table sends general abdominal pain to อายุรกรรม and reserves ศัลยศาสตร์ for a mass, anal symptoms or GI bleeding.)
- Shows: a **number** the patient said became a vital (`pain_score`) and drove a rule; English end-to-end.
- Variation (corrections): say “7”, and when the confirm question comes say “sorry, I meant 4, it's more of a dull ache” — the level-2 path drops, the nurse summary shows severity 4, and the interview continues to OPD Internal Medicine.

## 4 · Fever — routine, and the safety screen must NOT fire (`ws_th_fever_no_spo2`)

**Patient (th), 09900001:** “มีไข้ ปวดเมื่อยตัว มาสองวันค่ะ” → breathing “ปกติค่ะ” → “ไม่มีค่ะ” to danger signs, chemo, rash → **thermometer card** (37.8) → **cuff card** (normal) → onset “สองวัน” → associated “ไม่มีค่ะ” → weight/height → explanation → follow-up “ไม่มีแล้วค่ะ”.

**Expected:** ~11 turns.
- Level **4**, department **OPD เวชปฏิบัติทั่วไป (opd_general)** — routing table `fever → opd_general` “อาการไข้ทั่วไป → OPD ทั่วไป”.
- Must ask `fv_danger` (confusion / dyspnea / stiff neck) and `fv_chemo` — the two level-2 gates for fever (`tt_fever_chemo`).
- **Must NOT ask** `uq_spo2` (no breathlessness) and **must NOT ask** `mh_suicide` — the bug from last week.
- Nurse review shows “📖 อิงคู่มือ หน้า …” on the explanation (RAG on) and device tags on temp/BP.
- Shows: every question is worded naturally by the model — but each still names the symptom the manual's question names (the guard refuses any rewording that drops one); measurement requests stay fixed.

## 5 · Stress — the safety screen MUST fire, routes to psychiatry (`ws_th_stress_asks_selfharm`)

**Patient (th), 09900002:** “เครียดมากค่ะ นอนไม่หลับมาหลายอาทิตย์ ร้องไห้บ่อย” → breathing “ปกติค่ะ” → gender → **`mh_suicide`** “มีความคิดอยากทำร้ายตัวเองหรืออยากตายไหมคะ” → “ไม่มีค่ะ ไม่เคยคิดแบบนั้น” → temp / cuff cards → onset → psychosis “ไม่มีค่ะ” → weight/height → explanation.

**Expected:** ~9 turns.
- Must ask `mh_suicide` as the **first** template question — wording may vary, it must ask about hurting yourself / ending your life.
- Level **4**, department **OPD จิตเวช (opd_psychiatry)** — routing table `mental_health → opd_psychiatry` (severe stress / insomnia conditions).
- Variation: answer “มีค่ะ บางทีก็คิด” → level **2**, emergency, staff notified — rule `psych_code_purple` *Risk of self-harm (Code Purple)*; disposes on the direct answer.

---

## After the five: the write-back

Pick scenario 4 or 5 in the nurse portal → approve → the publish dialog shows the
SBAR preview; the VN field is pre-filled from HIS (`current_visit`) or left for
the nurse → publish → `Mock HIS (demo only)` → `GET /api/visits` (Postman) or the
admin Database tab shows `second_location` set and `mfu_prescreen` stored. Re-publish
the same review → same queue number (idempotent).

## Known limits to state out loud

- Expected levels are the manual as *we* encoded it; they are not yet nurse-validated. The review step is where the nurse overrides, and every override is a candidate criteria edit.
- Speech recognition is Google today; a mis-heard word changes findings. Repeat the utterance if the transcript shows it wrong — the engine reacts to the transcript, not the audio.
- Gemini today, local model later: same prompts, same bodies (Postman *AI Model (local inference)*).
- After the disposition the level does not change from the booth: anything the patient adds (“เดี๋ยวค่ะ พูดผิด…”) is kept in the nurse's follow-up note, and the nurse decides. A device reading is never overridden by speech.
