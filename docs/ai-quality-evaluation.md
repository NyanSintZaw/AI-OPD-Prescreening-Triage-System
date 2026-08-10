# How good is our AI screening, and how would we know?

Round of 2026-08-10, prompted by a live report: *"I have a fever but I don't
have a headache"* and the booth went on asking about headache.

Two halves — what we measured in our own system, and what the literature
says about measuring systems like it. They are kept apart on purpose: the
research does **not** underwrite our numbers, and our numbers do not
generalise.

---

## Part 1 — What we measured

### The reported bug was real, and it was not where it looked

It looked like the interview ignoring an answer. It was the **complaint
category** being lost.

`_keyword_category` picks a category when the model returns none or
`generic`. It counted every keyword occurrence, negated or not:

```
"มีไข้ แต่ไม่ปวดหัว"  →  fever 1 hit, headache 1 hit  →  tie
                        tie rule: "don't guess"      →  category unresolved
                        unresolved                    →  generic question set
```

The generic set asks broadly, which is what the patient experiences as being
ignored. Keywords inside a negation scope now score nothing (NegEx-style
backward window, Thai and English cues, terminated by `แต่`/`but`). Covered
by `tests/screening/test_negated_keyword_category.py`.

### The rules engine was not the problem

Worth stating because it was the obvious suspect. A scripted interview where
the patient volunteers everything on turn 1 — complaint, age, duration, five
denials, one associated symptom — produces **zero** repeated symptom
questions; it goes straight to measurements. The engine credits `absent` the
same as `present`, and a question is resolved once every finding it targets
is known.

So repetition means the finding never arrived. That makes it an extraction
metric, not a dialogue redesign.

### Extraction, measured live

`scripts/run_extraction_eval.py` against `gemini-3.1-flash-lite`:

| | before | after |
|---|---|---|
| corpus | 70/71 | **71/71** |
| volunteered denials credited | *not measured* | **11/11** |

The eval previously scored only `present` findings, so the failure class the
patient actually feels was invisible to it. It now scores `expect_absent`
(a denial that must come back as `absent`) and `expect_category` (never
categorise on a denied symptom), with 11 new cases built from the reported
sentence in Thai and English, plus the mirror case and multi-denial openers.

Two more defects fell out of running it:

- **Vertex was unreachable from any script.** `.env` ships a *relative*
  credential path and nothing resolved it, so anything that did not
  incidentally import `surveillance_extractor` fell back to gcloud ADC and
  got 403. `build_chat_model` now configures its own environment.
- **A Thai `เวียนหัว` (dizzy) opener extracted nothing.** Turn 1 offered a
  hand-listed opener vocabulary; `vertigo` belongs to the ear template, which
  turn 1 never offers. That is a chicken-and-egg — the finding that would
  select the template is the one withheld. Turn 1 now offers every finding
  any template asks about, derived from the criteria. (+41 findings on the
  first prompt only; later turns stay bounded, which is where precision
  matters.)

### Triage accuracy, measured live

There is a triage harness — `scripts/run_triage_eval.py` over
`evals/vignettes.json`, 65 labelled vignettes, multi-turn against the real
model, scoring level, department, category, must-ask coverage and validator
leaks, with QWK and a Clopper-Pearson interval on the undertriage rate.

**The first run reported 27.8% undertriage with five critical misses. That
number was wrong, and the way it was wrong is the lesson.**

The harness answers the booth by regex-matching each question against a
vignette's `answers` list, and fell back to **"no"** when nothing matched.
Confirm-gate questions have synthesized ids that match nothing — so the
simulated patient denied its own opening. The anaphylaxis vignette says
*"ปากก็บวม"* (my lips swelled) and then answered *"no"* to *"do you have lip
swelling?"*. The palpitations vignette describes blacking out yesterday and
then denied syncope. Four of the five critical misses were manufactured this
way; 9% of all patient turns in that run were unmatched defaults.

Re-running those five with the default corrected: all five reach level 2
emergency, **in 2-3 turns instead of 9-11** — the gate now gets its answer
and fires immediately.

Two things follow. First, a confirm question exists *only* because the
patient already said the thing, so affirming is the right default. Second,
and more important: **an eval that silently substitutes an answer can invent
a safety defect.** Unmatched question ids are now recorded per vignette so a
corpus gap is visible instead of reading as an engine failure.

The same class of bug appeared twice in one day — once here, once in a
throwaway harness written before this one was found. Any simulated patient
needs a truthful fallback, not a convenient one.

---

## Part 2 — What the literature supports

Deep-research round, 25 sources fetched, 120 claims extracted, 25 verified
adversarially, **15 killed**. Read the kills — they matter more than the
survivors here.

### Use as design templates

- **Fixed case set, gold-standard acuity, exact-match accuracy.** The
  reusable shape is 2,000 curated MIMIC-IV-ED cases with nurse-assigned ESI,
  run under two input conditions: symptoms only, and symptoms plus vital
  signs. That second split is exactly ours — free text alone versus free text
  plus a cuff reading. *(npj Digit Med 2025; PhysioNet MIMIC-IV-Ext-CDS)*
- **Report the error directions separately.** Errors are bidirectional in
  every system tested, and the two directions carry different harm. One
  worked example weights undertriage of a high-acuity patient 5× an
  overtriage. *(Schmieding et al., JMIR 2022; JMIR Med Inform 2026)*
- **Retrieval grounding beat model scale.** Holding the backbone constant,
  RAG over guideline sections plus prior similar cases lifted 5-level
  accuracy 0.542 → 0.802. Single-centre, n=236. Our RAG is explanation-only
  today — this is the one intervention with a large measured effect that we
  have not tried on the decision path. *(JMIR Med Inform 2026)*

### The number that matters most to us

Frontier LLMs asked to **assign the acuity level directly** plateau at
**~58–66% exact match** on real ED cases — below human nurse-nurse agreement
— adding vital signs buys ~2 points, and they are weakest at level 1.
Errors are directionally biased, not random (GPT-4 median ESI 2.0 vs humans'
3.0). *(npj Digit Med 2025; JAMA-adjacent 2024 studies)*

**This is consistent with our architecture but does not endorse it.** The
research was explicit: no verified source recommends the
extract-findings/rules-decide split. The inference is ours. What the
literature supplies is a ceiling on the alternative, not a proof of our
choice.

### Do not cite these — they were refuted

16 claims died in verification, clustering on *"the field standardly does
X"*: that vignette audits are the standard design (0-3), that exact-match
plus directional range accuracy is the standard metric pair (0-3), that
paired comparison against expert raters is standard (0-3), that separate
under/overtriage reporting is the standard framing (0-3). Individual studies
do these things. "The field does this" does not survive checking.

**All three i2b2/n2c2 assertion claims were refuted 0-3**, including the
LLaMA2 0.98-F1-on-Negated figure and the NegEx/ConText recall-ceiling claim.
Any future claim about negation-detection accuracy needs fresh sourcing.

### Two honest gaps

- **Negation:** one surviving claim, and it is indirect — zero-shot
  cross-lingual negation *scope* resolution reaches 94.2 token-F1 on Spanish
  clinical text, with gold cues, only ~3 F1 above a punctuation heuristic,
  2021-vintage mBERT. **Zero Thai or Southeast Asian coverage anywhere.**
  Whether Thai particles (ไม่, ไม่มี, ยังไม่, เปล่า) and their scope behaviour
  break cue lexicons ported from English is unstudied. Our fix is a
  reasonable port; it is not an evidenced one.
- **Redundant-question avoidance and dialogue-state tracking:** *nothing
  survived verification.* No established practice to copy. Treat our design
  as unevidenced rather than validated.

### Nothing here transfers as a target

Every triage figure comes from US ESI, Hong Kong HKAETG, or English/German
consumer vignettes. None involves Thai, MOPH 5-level criteria, voice input,
patient-authored free text, or a kiosk. Transfer the study *designs* and the
*metric structure*. Do not transfer an accuracy number as a target or a
baseline — including as something to beat.

---

## What to build next

A **triage-accuracy eval** alongside the extraction one, because the extraction
eval cannot see a wrong level. Concretely:

1. A case set of full presentations with a nurse-assigned MOPH level as
   ground truth — from our own reviewed sessions, since no Thai MOPH set
   exists to borrow.
2. Score exact-match level **and** report the directions separately, with
   undertriage as the headline safety number.
3. Run the two input conditions the benchmark design uses and we already
   have: free text alone, and free text plus booth vitals.
4. Only then consider RAG on the decision path — it is the intervention with
   the largest measured effect, and it is also the one most likely to blur
   the LLM/rules boundary this system is built on. Measure before adopting.

One thing the research could not tell us: how to score the extraction layer
itself. No verified benchmark scores *"did the model emit the right finding
ids, with the right present/absent state, and a faithful evidence quote"* —
which is the only thing our LLM is responsible for. `run_extraction_eval.py`
appears to have no precedent to copy, which is a reason to keep investing in
it, not a reason to distrust it.
