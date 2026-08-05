# Demo Script — How the Criteria Decide (5 scenarios)

The other two demo documents show the **experience** (booth flow, voice, slip,
write-back). This one shows the **decision**: which rule fired, why it fired,
and what would have had to be different for the patient to end up somewhere
else.

Every scenario is an **A/B**: the same patient says almost the same thing, and
one changed input moves them between departments — or between OPD and the
emergency room. That contrast is the demo. A single run only shows *an* answer;
the pair shows that the answer is **derived**, not guessed.

> **Audience:** clinicians, hospital IT, and anyone who needs to be convinced
> the AI is not the one deciding. Presenter needs the **nurse portal trace**
> open — that is where the rule ids and citations live.
> **Runtime:** ~25 min for all five, ~12 min for the short set (S1 → S3 → S5).

**Related docs:** [demo-runbook.md](demo-runbook.md) (booth UX, voice setup,
reset commands) · [demo-script-meeting-2026-07.md](demo-script-meeting-2026-07.md)
(identity, resume, history intake) · [criteria-standards.md](criteria-standards.md)
(where each rule comes from) · [vital-bounds.md](vital-bounds.md) (plausibility
filter, used in S3).

---

## 0. The one slide: the decision ladder

Say this once at the start and refer back to it in every scenario.

```
  patient utterance ─┐
  cuff / booth vitals ┼─► ① PLAUSIBILITY FILTER  (vital_bounds)
  age from HIS       ─┘        impossible numbers discarded + re-asked
                                        │
                                        ▼
                        ② LEVEL-1 CRITERIA        20 rules → level 1 (Red)
                        ③ DANGER VITALS           16 rules → level 2, age-banded
                        ④ FAST TRACKS             BEFAST, MI → level 2
                        ⑤ DEPARTMENT RULES        22 rules → level 2
                        ⑥ TRIAGE TUPLES           19 combos → level 2
                                        │   all evaluated every turn;
                                        │   most severe hit wins
                                        ▼
                        ⑦ PAIN / DISTRESS SCALE   ≥8 + high-risk → 2 · ≥7 → 3
                        ⑧ RESOURCE BAND           levels 3 / 4 / 5
                                        │
                                        ▼
                        ⑨ DEPARTMENT ROUTING
                             level ≤ 2 ................ Emergency, always
                             age < 15 ................. Pediatrics
                             specialty criteria met ... that clinic
                             not met .................. general OPD first
```

**Three sentences for the audience:**

1. The LLM extracts findings from what the patient says and phrases the
   questions. It never picks a level. Steps ② – ⑨ are ordinary code reading a
   nurse-approved JSON document.
2. Every rule is evaluated on every turn. They **all** fire independently; the
   engine sorts the hits and takes the most severe. The nurse sees the full
   list, not just the winner.
3. The patient is never told a level or a color. They are told a **department**.

---

## Pre-flight

Full setup in [demo-runbook.md §0](demo-runbook.md). The criteria-specific bits:

```bash
docker compose up -d                                  # postgres + mock HIS
cd hospital-hotline-assistant-api
uv run python scripts/init_db.py                      # migrations + seed criteria
uv run python scripts/seed_screening_criteria.py --activate-v2   # ← demo on v2
uv run uvicorn app.main:app --reload
cd ../hospital-hotline-assistant-web && npm run dev
```

**Which criteria version?** Every verdict below is identical on **v1 and v2** —
deliberately, so you can demo on either. v2 is recommended because it adds the
breadth (24 complaint categories vs 14, 19 triage tuples vs 6) and authors the
plausibility bounds with nurse-written Thai. Show the active version in
**Admin → Screening Criteria**; the version is pinned per session, so a mid-demo
activation never changes a running interview.

**Tabs to have open:** Kiosk `/patient` · Nurse `/nurse` · Admin `/admin`
(Screening Criteria tab, so you can jump to a rule when someone asks).

### The cast (seeded HIS, ages as of Aug 2026)

| VN (visit ID) | Name | Age | Used in |
|---|---|---|---|
| `990000000000000001` | สมชาย ใจดี | 41 | **S1** — routing by specialty acceptance |
| `990000000000000005` | ประเสริฐ สุขสม | 78 | **S2** — fast track / level-1 shock |
| `990000000000000007` | มาลี วงศ์สว่าง | 51 | **S3** — bounds → rest → danger vital |
| `990000000000000008` | ภูมิ รักเรียน | 6 | **S4** — age bands |
| `990000000000000006` | Anucha Thongdee | 24 | **S4** — the adult half of the A/B |
| `990000000000000004` | Waraporn Srisuk | 33 | **S5** — history-driven tuple |

---

## S1 — Nothing fires: the band, and the specialty gate (≈5 min)

**Branch on show:** ⑧ resource band + ⑨ routing with `specialty_conditions`.
**Point:** most patients trip no rule at all. The engine still has to place
them, and it does it by *acceptance criteria*, not by keyword.

**Patient:** สมชาย (41), VN `…001`. Earache for two days.

| # | Say / do | What happens |
|---|---|---|
| 1 | 🎙 "ปวดหูข้างขวามาสองวันครับ" | `ear` template selected |
| 2 | Answer the red flags **"ไม่มี"** — and when asked about **discharge from the ear**, say 🎙 **"มีน้ำใส ๆ ไหลออกจากหูนิดหน่อยครับ"** | `ear_discharge` = present |
| 3 | BP card appears → `118 / 76`, pulse `72` | Plausible, accepted, fires nothing |
| 4 | Weight/height card at the end | — |
| 5 | **Verdict** | **Level 4 (Green) → OPD ENT** |

**Now the A/B — rerun and deny the discharge** (reset the visit first, or use
another VN): everything else identical, but answer **"ไม่มี"** to discharge,
tinnitus, hearing loss and vertigo.

| | Findings | Verdict |
|---|---|---|
| **A** | `ear_pain` + `ear_discharge` | Level 4 → **OPD ENT** |
| **B** | `ear_pain` only | Level 4 → **OPD General Practice** |

**Say this:** the ENT clinic doesn't accept ear pain — it accepts *hearing loss,
tinnitus, ear discharge, or severe vertigo*. Those four findings are the
`specialty_conditions` on the `ear` routing entry, written by the hospital. Miss
them all and the patient is screened at general OPD first, exactly as the paper
manual instructs. **Same complaint, same level, different door — decided by one
finding.**

**Show in the nurse trace:** `resource_band_level_4` — "no red flags; symptom
profile fits level 4" — then the routing reason, either *"Meets opd_ent
acceptance criteria"* or *"Does not meet opd_ent acceptance criteria — screened
at general OPD first"*, each with its MFU citation.

**If asked "what makes it level 4 and not 3 or 5?"**
Level 5 = nothing present at all (a records/certificate visit). Level 4 = at
least one finding. Level 3 = two or more *systemic* findings (fever, vomiting,
diarrhea, dyspnea, confusion, fainting, bleeding…) or four or more findings
total. Demo it live if you have a minute: fever **+ vomiting + diarrhea** →
level 3, still OPD General. It is a deliberately conservative local heuristic,
labelled as such in the citations — not a copied standard.

---

## S2 — Words alone are enough: fast track, tuple, and the level-1 override (≈5 min)

**Branch on show:** ④ fast tracks + ⑥ triage tuples firing together; then ②
level-1 criteria overriding everything.
**Point:** an emergency can be decided from *speech only*, before any
measurement — and the gate stops the interview the moment it fires.

**Patient:** ประเสริฐ (78), VN `…005`.

### Take A — two rules fire on the first turn

| # | Say | What happens |
|---|---|---|
| 1 | 🎙 **"เจ็บแน่นหน้าอก ร้าวไปที่กราม แล้วก็เหงื่อแตกครับ"** ("chest tightness radiating to my jaw, and I'm sweating") | `chest_pain`, `chest_pain_radiating`, `diaphoresis` extracted |
| 2 | — | **Emergency banner immediately.** No BP card, no weight/height, no follow-up question |

**Verdict: Level 2 (Orange) → Emergency.** One nuance to narrate (added Aug
2026): findings inferred from the opening sentence are **confirmed with one
verbatim question each before the banner** — the booth never declares an
emergency from inferred words alone, only from what the patient confirmed or
a machine measured. Expect one or two quick ใช่/ไม่ questions between the
sentence and the alert. Two independent rules then fire:

- `ft_mi_chest_pain` — heart-attack fast track (chest pain radiating to
  neck/jaw/shoulder)
- `tt_chest_pain_diaphoresis` — chest pain **+** sweating

**Say this:** they agree here, which is the point — the criteria are
deliberately redundant on the killers. Had he only mentioned the sweating and
not the radiation, the tuple alone still catches him. The nurse trace lists
**both** hits with both citations; the engine took the most severe (a tie at
level 2) and short-circuited the interview. Notice what it *didn't* do: it
never asked for blood pressure. Once a level-2 rule fires there is nothing a
measurement could add — get him to ER.

### Take B — the same patient, milder words, and a number that outranks everything

Reset the visit and rerun:

| # | Say / do | What happens |
|---|---|---|
| 1 | 🎙 **"แน่นหน้าอกนิดหน่อยครับ"** — chest tightness only, deny radiation and sweating | `chest_pain` only → **no rule fires**, interview continues |
| 2 | BP card → enter **`86 / 48`**, pulse `104` | — |
| 3 | — | **Level 1 (Red) — Immediate.** `l1_adult_shock_bp` |

**Say this:** 86/48 is shock. It jumps the whole ladder — level 1 is checked
first and nothing below it can lower the verdict. Colour Red, response time
"Immediate", and the nurse portal shows it against the MOPH lifesaving
criterion. The same patient, the same complaint, two levels apart, on one
number the machine measured.

---

## S3 — Numbers decide: the plausibility filter, the rest window, the danger vital (≈7 min)

**Branch on show:** ① plausibility bounds → the 15-minute BP protocol → ③
danger vitals. Optional ④ BEFAST.
**Point:** the objective rail is the most powerful input in the system, so it
is also the most carefully guarded. **"Impossible" and "dangerous" are
different questions and the engine asks them in that order.**

**Patient:** มาลี (51), VN `…007`. Dizzy and heavy-headed since morning.

| # | Say / do | What happens |
|---|---|---|
| 1 | 🎙 **"เวียนหัว มึน ๆ มาตั้งแต่เช้าค่ะ"** | `headache` template; the **BEFAST stroke check** appears with one chip per symptom |
| 2 | Tap **"ไม่มีอาการเหล่านี้" (none of these)** | No fast track. Interview continues |
| 3 | BP card → type **`400 / 220`** (a slipped cuff, or a fat-fingered kiosk entry) | ⚠ **Refused before the rules ever see it.** Nurse-authored bilingual message, the card stays open, **no rest timer, no emergency**, nothing sent as a conversation turn |
| 4 | Measure properly → **`190 / 115`** | **Rest-first protocol:** "please sit and rest 15 minutes." Reading kept as provisional, assessment saved, call ends politely. **Still no emergency** |
| 5 | Expire the window (demo shortcut): `psql "$DATABASE_URL" -c "UPDATE bp_rest_windows SET rest_until = now() WHERE resolved_at IS NULL;"` | — |
| 6 | Re-enter VN `…007` → confirm → **ทำต่อ** → the interview resumes **at the BP card** → **`192 / 118`** | **Level 2 (Orange) → Emergency.** `dv_adult_bp_crisis` |

**The three-way distinction to spell out — this is the heart of the scenario:**

| Reading | Verdict | Why |
|---|---|---|
| `400/220` | **discarded** | No human has that blood pressure. It is a broken measurement, not a finding |
| `190/115` | **rest 15 min** | Real and high — but a single booth reading is not a diagnosis (white-coat effect) |
| `192/118` after rest | **Emergency** | Confirmed hypertensive crisis, `dv_adult_bp_crisis` (SBP > 180 or DBP > 110) |

**Say this:** if we had merged "impossible" into "dangerous", 400/220 would be
*more* than 180 and would have driven an emergency disposition off a reading
that never happened. So the bounds are an input filter and are deliberately
far wider than any clinical threshold — 250/130 is accepted and *does* fire the
crisis rule. And the impossible reading does **not** open the rest window:
making a patient sit 15 minutes for a cuff that slipped would be both pointless
and alarming.

**Show in the nurse portal:** the rejected `400/220` appears **flagged with the
reported value, struck through** — not as a blank. A blank would read as "not
measured", which is a completely different clinical signal from "the booth was
told 400/220". The refused numbers are never published to the hospital record.

**Optional ad-lib (30 s) — the fast track:** rerun step 2 and tap **"พูดไม่ชัด"
(slurred speech)** instead of "none of these". `ft_stroke_befast` fires
instantly → level 2 → Emergency, **before** BP is ever requested. One chip, one
rule, no measurement needed.

---

## S4 — Age the patient never typed (≈4 min)

**Branch on show:** ③ danger vitals evaluated **per age band** + ⑨ pediatric
routing.
**Point:** the same number means different things at different ages, and the
age comes from the hospital's own record.

Run the **same complaint twice**, on two different patients.

### A — ภูมิ (6), VN `…008`, Thai

| # | Say / do | What happens |
|---|---|---|
| 1 | 🎙 **"ลูกมีไข้แล้วก็ไอค่ะ"** | `fever` template |
| 2 | Deny the danger question (confusion / trouble breathing / stiff neck) | — |
| 3 | Temperature card → **`39.2`** | Fever confirmed |
| 4 | BP card → **`98 / 60`**, **pulse `126`** | — |
| 5 | — | **Level 2 (Orange) → Emergency.** `dv_child_5_10y` (age 5–10: HR > 120, RR > 30, or SBP < 90) |

### B — Anucha (24), VN `…006`, English, same story

Fever and cough, `38.5 °C`, `118/76`, pulse `96` → **Level 4 (Green) → OPD
General Practice.** No rule fires.

**Say this:** nobody typed an age. The engine read the birthdate from the linked
visit, picked the **5–10 years** band, and applied that band's thresholds. A
pulse of 126 is an emergency for a six-year-old and unremarkable for an adult —
the adult threshold is 120 at rest, the 10–15 band is 100, and for an infant
under one month a temperature of 38.0 °C is *by itself* a level-2 rule. Sixteen
danger-vital rules, each scoped to a band.

**The third data point, if you have 30 more seconds:** rerun ภูมิ with pulse
**`112`** instead of 126 — below the band threshold, so nothing fires: **level
4 → OPD Pediatrics**. Same child, same fever, one rung on the pulse. And note
the department: under-15 goes to Pediatrics for every non-obstetric complaint,
which is why the adult with an identical complaint landed at General Practice.

---

## S5 — What they told us 60 seconds ago changes the verdict (≈5 min)

**Branch on show:** ⑥ triage tuples driven by a **risk factor**, not a symptom;
plus ⑦ the pain-scale branch.
**Point:** triage is a combination, not a keyword. A finding that is harmless
alone becomes level 2 in company.

**Patient:** Waraporn (33), VN `…004`, **first-time patient**, English.

| # | Say | What happens |
|---|---|---|
| 1 | First-visit history questions, asked aloud one at a time. On chronic conditions: 🎙 **"High blood pressure since 2023"** | `hypertension_history` recorded → written to her HN record |
| 2 | 🎙 **"I'm seven months pregnant and I've had a bad headache since this morning."** | `pregnancy` + `headache` extracted |
| 3 | — | **Level 2 (Orange) → Emergency.** `tt_pregnancy_hypertension` — suspected pre-eclampsia |

**The A/B:** the exact same sentence in step 2, from a patient with **no**
hypertension history → **level 4 → OPD OB-GYN**. Ordinary antenatal headache.

**Say this:** neither finding is an emergency by itself. Pregnancy is not an
emergency. A history of high blood pressure is not an emergency. Together they
are suspected pre-eclampsia and the criteria force level 2. Nineteen of these
combinations are encoded — chest pain + sweating, fever + chemotherapy, rash +
lip swelling with breathing trouble, chronic cough + coughing blood. **And the
risk factor came from the booth interview 60 seconds earlier, not from her
complaint** — which is exactly why the history intake writes to the hospital
record *and* feeds the assessment.

**The pain branch, if there's time (worth 60 s):** ask for the pain score.

| Answer | Verdict | Rule |
|---|---|---|
| Headache, pain **7** | Level 2 → Emergency | `surg_severe_pain_critical_site` — pain ≥ 7 at head, chest or abdomen |
| **Knee** pain, pain 7 | Level 3 (Yellow) → OPD Orthopedics | `scale_severe_no_red_flags` — severe pain, no red flags |
| Knee pain, pain 3 | Level 4 → OPD Orthopedics | resource band |

Severe pain is read **against the site**. Seven out of ten in the head is an
emergency; seven out of ten in a knee is urgent, not emergent. Both are labelled
local MFU heuristics in the citation, not borrowed from a foreign standard.

---

## Coverage — what the five scenarios prove

| # | Ladder step | Fired rule(s) | Verdict |
|---|---|---|---|
| S1 A/B | ⑧ resource band, ⑨ specialty acceptance / fallback | `resource_band_level_4` | L4 → **ENT** vs **General OPD** |
| S2 A | ④ fast track + ⑥ triage tuple, gate short-circuit | `ft_mi_chest_pain`, `tt_chest_pain_diaphoresis` | L2 → Emergency |
| S2 B | ② level-1 criteria override everything | `l1_adult_shock_bp` | **L1 Red** → Emergency |
| S3 | ① bounds → BP rest protocol → ③ danger vitals | `dv_adult_bp_crisis` | discarded → rest → L2 |
| S3 ad-lib | ④ fast track from a single chip | `ft_stroke_befast` | L2 → Emergency |
| S4 A/B | ③ age-banded danger vitals, ⑨ pediatric routing | `dv_child_5_10y` | L2 vs **L4 → Pediatrics** |
| S5 | ⑥ tuple from a history risk factor | `tt_pregnancy_hypertension` | L2 vs **L4 → OB-GYN** |
| S5 pain | ⑤ department rule vs ⑦ scale escalation | `surg_severe_pain_critical_site`, `scale_severe_no_red_flags` | L2 vs L3 |

Not demonstrated live (mention only if asked): the remaining 19 level-1
criteria (cardiac arrest, airway obstruction, apnea, active seizure, pediatric
cyanosis…) — they need a patient who cannot use a kiosk, which is the honest
limit of a self-service booth. They exist for the case where a companion is
answering.

---

## Questions you will get

**"What if the AI extracts the wrong finding?"**
Then the rules act on a wrong finding — and that is the failure mode we
designed *for*, which is why the LLM's job is deliberately small. It never
picks a level, it fills in a finding id from a fixed catalogue of 149. Every
extraction is written to the audit trail, so the nurse can see the sentence and
the finding side by side and reroute. A red-flag question whose answer didn't
parse is re-asked exactly once, then left unknown rather than guessed — and an
unknown finding can never satisfy a rule.

**"Can we change a threshold without calling you?"**
Yes. The whole document — thresholds, rules, questions, department routing, the
plausibility bounds — is one JSON document with a draft → review → approve →
activate lifecycle in the admin portal. Changing SBP 180 to 170 is an edit and
an approval, not a release. Sessions pin the version they started on, and the
review screen diffs the change.

**"Where does each rule come from?"**
Every rule carries a citation, rendered in the nurse trace. MOPH ED Triage is
the governing standard; the MFU manual is the local source; the ESI v5 handbook
is cited only where specific factual content was referenced. Local heuristics —
the resource band and the pain escalation — say so in the citation rather than
borrowing someone else's authority. Full provenance in
[criteria-standards.md](criteria-standards.md).

**"What if two rules disagree?"**
They can't, structurally. Every rule only ever *raises* acuity; the engine takes
the most severe hit. There is no rule that lowers a level, and no override chain
— what the engine decides is what gets persisted.

**"Why didn't it ask for blood pressure?"**
Because that complaint template has no BP question. Sixteen of the 24 v2
templates ask for BP; wound/skin, gynecology, breast, limb-vascular, forensic,
GI, rash and administrative do not. It is a per-template clinical decision in
the criteria, editable by the hospital — not a hard-coded rule.

---

## Appendix — verdict cheat sheet

Keep this open on a second screen. Every row is verified against the seeded
criteria (both v1 and v2).

| Input | Level | Department | Rule |
|---|---|---|---|
| ear pain + ear discharge, 41 | 4 | OPD ENT | resource band + specialty match |
| ear pain alone, 41 | 4 | OPD General | specialty criteria not met |
| sore throat alone, 33 | 4 | OPD General | fallback |
| sore throat + allergy symptoms, 33 | 4 | OPD ENT | specialty match |
| no findings, 41 | 5 | OPD General | resource band |
| fever + vomiting + diarrhea, 24 | 3 | OPD General | 2 systemic findings |
| chest pain radiating + sweating, 78 | 2 | Emergency | `ft_mi_chest_pain` + `tt_chest_pain_diaphoresis` |
| chest pain, SBP 86 | **1** | Emergency | `l1_adult_shock_bp` |
| dizzy, BP 192/118, 51 | 2 | Emergency | `dv_adult_bp_crisis` |
| dizzy + slurred speech, 51 | 2 | Emergency | `ft_stroke_befast` |
| dizzy, BP 138/84, 51 | 4 | OPD Internal Medicine | resource band |
| fever + cough, pulse 126, **age 6** | 2 | Emergency | `dv_child_5_10y` |
| fever + cough, pulse 112, age 6 | 4 | OPD Pediatrics | under-15 routing |
| fever + cough, pulse 96, age 24 | 4 | OPD General | resource band |
| pregnant + headache + hypertension history | 2 | Emergency | `tt_pregnancy_hypertension` |
| pregnant + headache, no history | 4 | OPD OB-GYN | resource band |
| headache, pain 7 | 2 | Emergency | `surg_severe_pain_critical_site` |
| knee pain, pain 7 | 3 | OPD Orthopedics | `scale_severe_no_red_flags` |

**Rejected by the plausibility filter:** `400/220`, `300/220` (impossible half
discards the pair), `80/120` (swapped), `50 °C`, `900 kg`, height `1.7` cm.
**Accepted and dangerous:** `250/130` → `dv_adult_bp_crisis`.

### Reset between runs

```bash
cd hospital-hotline-assistant-api
uv run python scripts/reset_demo.py           # sessions, BP locks, HIS reseed
uv run python scripts/reset_his.py 990000000000000005    # one visit only
psql "$DATABASE_URL" -c "DELETE FROM bp_rest_windows;"   # clear a rest lock
```

### If a verdict comes out different on stage

- **Wrong level, right department** → almost always an extraction miss. Open the
  nurse Conversation tab: the sentence and the extracted findings are side by
  side. Rephrase closer to the script and rerun.
- **No emergency where the table says emergency** → check the vital was actually
  accepted (a rejected value is flagged, not silently missing) and that the
  visit is linked, so the engine has an age.
- **"Interview asks for my age"** → the visit wasn't linked; re-enter the VN.
- **Everything routes to General OPD** → criteria not seeded:
  `uv run python scripts/seed_screening_criteria.py`.
- The regression suite covers every row of the cheat sheet:
  `uv run pytest -m "not integration"`.
