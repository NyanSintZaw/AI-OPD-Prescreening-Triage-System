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

### The corrected run (65 vignettes, gemini-3.1-flash-lite, criteria v2)

| | first run | corrected |
|---|---|---|
| **undertriage** | 27.8% (5/18) | **0.0% (0/18)**, CI95 0.0–18.5% |
| QWK | 0.798 | **0.940** |
| level exact | 80.0% | 86.2% |
| level within 1 | 92.3% | **100.0%** |
| category / department | 93.8% / 86.2% | 93.8% / 93.8% |
| validator leaks | 0 | **0** |
| avg turns | 8.0 | 7.1 |
| passed | 45/65 | 50/65 |

By language, both at zero undertriage: th QWK 0.954, exact 87.5%; en QWK
0.915, exact 84.8%. Every remaining failure is a category or department
label, not a level.

**Read the interval, not the point estimate.** Zero misses out of eighteen
critical vignettes gives a 95% upper bound of **18.5%** — the corpus is too
small to claim a low undertriage rate, only to say none of these eighteen
was missed. Widening the critical set is worth more than any further tuning.

And the standing caveat: gold levels come from the criteria's own rules, so
this measures the pipeline, not the criteria's clinical validity. Nothing
here is a clinical claim.

### After the 2026-08-11 fixes (one clean run, committed tree)

```
n=65 passed=51 | UNDERTRIAGE 0/18 (CI95 0.0-18.5%) | QWK 0.946
level exact 87.7% | within-1 100% | category 92.3% | dept 93.8%
leaks 0 | avg turns 7.2
th: QWK 0.953 exact 87.5% | en: QWK 0.932 exact 87.9% | both 0 undertriage
```

Three engine defects fixed, each found by measurement rather than reading:

- **`high_fever` was never derived.** It counts in `SYSTEMIC_FINDINGS`,
  where two systemic findings take a case from level 4 to 3, and the catalog
  defines it as >38.5 C — but `apply_objective_findings` only ever set
  `fever`. A thermometer at 38.9 scored one systemic finding, not two.
- **A volunteered symptom closed compound red flags.** `_is_resolved`
  treated a red flag as answered once *any* of its findings was present, so
  a patient who mentioned fever silently deleted the rest of the question.
  `meningitis_suspect` (fever + stiff neck, level 2) could therefore never
  fire. The widest-reaching of the three.
- **The confirm gate borrowed another template's wording**, asking *"is
  something stuck in your ear?"* to confirm a throat foreign body. A
  truthful "no" erased a level-2 airway finding.

**What did not move, and why it matters more than what did.**
`ur_th_flank_fever` still lands level 4 with a 38.9 C fever in the vignette,
because the urinary template has **no temperature question** — the reading
is never taken, so deriving `high_fever` correctly cannot help. Fixing how a
number is interpreted does nothing where the number is never collected.

Five of the eight borderline cases are **criteria gaps, not defects**:
isolated adult chest pain, recurrent palpitations, hemoptysis,
pyelonephritis and first-trimester bleeding have no rule giving them a
floor, so `_resource_band` correctly caps a clean single-complaint
presentation at level 4. The vignettes assert acuity the criteria do not
encode. That is a question for the nurses who own the criteria.

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

---

## Part 3 — Is the architecture itself defensible? (2026-08-12)

Second research round, re-scoped to AI engineering only — no triage scales,
no medical regulation. 112 agents, zero errors, adversarial verification.

### The split is a named, published pattern

"LLM converts speech to structured facts; a deterministic engine performs all
inference" is **neurosymbolic AI / LLM-as-semantic-parser**, and two published
systems are directly comparable:

- **Logic-LM** (Findings of EMNLP 2023) — LLM translates the problem into a
  symbolic formulation, "a deterministic symbolic solver performs inference".
- **ProCDS** (MICCAI 2025) — SWI-Prolog + Llama3-8B on vLLM for clinical
  decision support, motivated explicitly by hallucination containment.

**Our version is strictly more constrained than either.** In both papers the
LLM authors the *logic* as well as the facts. Ours emits only facts, against a
fixed catalog, with hand-authored version-pinned rules. Cite this as "a named
published pattern", never as "the same architecture".

### Do NOT claim it is more accurate

Three separate accuracy claims for the hybrid split were **refuted 0-3**,
including Logic-LM's headline +39.2% (closed-world logic benchmarks, not
conversational extraction) and ProCDS's 99.5% vs ~80% end-to-end.

**No surviving evidence shows this split beats end-to-end LLM classification
on accuracy in any domain resembling ours.** The honest justification is
auditability, determinism and version control — a nurse can read why a level
fired, and the same input gives the same output. That is worth a lot here.
It is not an accuracy argument, and overselling it as one would not survive
scrutiny.

### Constrained decoding is vindicated

The "grammar constraints degrade reasoning" claim **does not hold as a general
result**. JSON-schema-constrained decoding matched or beat unconstrained
generation on both reasoning and extraction tasks; grammar-constrained
decoding lifted clinical extraction F1 from **0.062 to 0.413**. Where
constraints did lose accuracy, the cause was **subword/token misalignment in
the constraint implementation**, not constraint itself.

### One finding that is a live risk, and one guard we already have

**Schema enforcement is not a guarantee.** XGrammar — vLLM's preferred backend,
which is what our on-prem deployment will use — was the **most permissive
engine measured**. Re-validating emitted ids against the catalog is mandatory,
not belt-and-braces. *Checked: `nodes/ingest.py:245` gates every finding update
on `update.id in criteria.finding_catalog`, with no bypass. We are covered —
but this must never be removed.*

### Evidence quotes: auditability yes, accuracy no

Requiring a verbatim span per finding is a shipped pattern (Google
LangExtract flags unlocatable extractions with `char_interval=None`), and
quote-locatability works as an automatic ungrounded-extraction filter. But:

- the effect on task quality is **model-dependent** — macro-F1 up for two
  models, significantly **down** for a third
- it **reduces coverage** and raises invalid-output rates for every model
  tested
- a quote that verifiably appears is **not** a quote that supports the finding:
  only **48-79%** of quoted predictions were judged actually supporting, and
  self-judging does not close the gap
- even flagship models produced quotes failing exact-substring verification in
  **9-17%** of runs

**This is the finding that matters most for us.** In this architecture a
missed extraction is the *only* way a rule can fail to fire — so anything that
reduces coverage is a direct safety cost. We require evidence quotes AND
containment-check them, and we have never measured what that costs in recall.
That experiment is a diff on the extraction schema plus a run of
`run_extraction_eval.py`, and it is the single highest-value thing left.

### Where the eval budget belongs

Logic-LM's own limitation section identifies the natural-language-to-symbolic
translation step as the dominant failure point. Ours fails **silently** — a
finding that never arrives simply never fires a rule, with no error anywhere.
That is an argument for spending on the extraction eval, not the rules tests,
and it is what we have been doing.

### Two honest evidence gaps

Nothing survived on either of these, and no claims were even proposed:

1. **Extraction failure modes at the level we depend on** — recall/miss rates
   for conversational clinical IE, negation and hedging errors, ontology
   coverage when mapping free speech onto a fixed id list, and the effect of a
   100+ candidate list on recall and false positives. That last one is not
   academic: turn 1 now offers ~131 findings, and the precision cost is
   unmeasured.
2. **Local 7B-14B open-weight models for structured extraction, and Thai IE.**
   Three incidental data points, none Thai, none an extraction-quality
   comparison.

Both are unresearched, not settled. For a Thailand-first deployment on on-prem
hardware, that means **our own extraction eval is the only evidence that will
ever exist for this system** — there is no external benchmark to defer to.

### Measured: should the finding ids be a schema enum? No. (2026-08-12)

`FindingUpdate.id` is a free-form `str`, so the vocabulary lives only in prompt
prose and an invented id is caught after the fact at `ingest.py:245`. The
obvious improvement is to put the offered ids in the JSON Schema as an enum so
constrained decoding makes an invalid id impossible. Measured first:

| channel | invalid rate |
|---|---|
| finding ids, turn 1 (131 offered, 3 runs) | **0 / 356 — 0.00%** |
| finding ids, multi-turn (515 calls) | **2 / 593 — 0.34%** (Wilson 95% CI 0.09–1.2%) |
| `complaint_category` | ~5% invented, **100% recovered** by `_closest_category` |

**Recommendation: do not add it**, and the reason is more interesting than the
rate. Both invalid ids were the same thing — the model emitting `urinary`, a
*category* id, into the finding slot, because it was reaching for "urinary
symptoms" and **no such finding was offered that turn**.

A constrained decoder cannot emit nothing. Faced with a concept it has no id
for, it must pick some offered id — turning a dropped extraction into a
*wrong present finding*. That is strictly worse here: a dropped finding leaves
the question unknown so the interview asks it, while a wrong one fires a rule.
It is also the exact failure `_catalog_lines` already documents from the Aug-5
eval (a cold pale leg extracted as the level-1 shock-skin finding).

Verified along the way, so nobody re-derives it: Gemini *does* pass a 131-value
enum through `convert_to_genai_function_declarations`, and `convert_to_openai_tool`
keeps it for the vLLM/XGrammar path — so it would work, at ~600 tokens per call
duplicating the prompt catalog, plus a per-call dynamic model needing an
`lru_cache`. It works; it is not worth it.

`ingest.py:245` stays. It is currently the only enforcement, and it is doing
its job at zero measured cost.
