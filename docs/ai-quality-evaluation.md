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

### Measured: RAG in the explain node makes English replies worse (2026-08-12)

First run ever with retrieval actually on (`--rag`; every prior number was
RAG-off). Aggregates: no change, as predicted — undertriage 0/18 both arms,
leaks 0 both, department identical; retrieval cannot reach the rules engine
by construction. All 44 non-emergency dispositions retrieved successfully
(avg 2993 chars). Latency: none measurable.

The reply text is where the effect is, and it is negative:

| EN non-emergency replies falling back to the canned template | count |
|---|---|
| RAG off | 5/25 |
| RAG on | **15/25** |

Mechanism, confirmed by direct probe: the retrieved passages push the model
into empathic openers — *"I understand you have been experiencing a
headache…"* — and `validator.py` flags bare `\byou have\b` as a diagnosis
leak. Both attempts fail validation → the patient gets the flat deterministic
template instead of a warm reply. Thai has no equivalent trigger phrase,
so 0 Thai replies flipped. The validator held (leaks stayed 0); the cost is
tone, not safety.

Two conclusions:

1. **`--rag` stays off by default.** The index holds clinician routing tables
   (lab thresholds, department lists) — nothing usable in a 2-4 sentence
   patient reply that may not name a diagnosis or another department. RAG
   here has value only if the manual ever gains patient-facing sections.
2. **The real bug is the validator's `\byou have\b` rule** — a false-positive
   generator on ordinary empathy, punishing warm English replies with or
   without RAG. Tightening it to require a condition noun after "have" would
   recover them. Queued (screening/ is mid-edit by the gender work).

## Measured: natural-dialogue + SpO2 + RAG observability release (2026-08-20)

Live smoke, 12 vignettes (th 6 / en 6) including the new behaviour cases,
`gemini-3.1-flash-lite`, criteria v2, same set run in both arms. Reports:
`evals/reports/2026-08-20T210103Z.md` (RAG off) and
`evals/reports/2026-08-20T210626Z.md` (RAG on).

| metric | RAG off | RAG on |
|---|---|---|
| passed | 12/12 | 12/12 |
| undertriage (expected ≤2) | 0/5 | 0/5 |
| QWK / level exact / within-1 | 1.0 / 100% / 100% | 1.0 / 100% / 100% |
| category / department match | 100% / 100% | 100% / 100% |
| validator leaks | 0 | 0 |
| **explain: template fallbacks** | **0/12** | **0/12** |
| explain: grounded in uploaded manual | 0/12 | **7/7 non-emergency** (5 emergency = fixed wording by policy) |
| rules-oracle disagreements | 0 | 0 |
| avg retrieval | — | 3,065 chars, ~100 ms |

### Re-run 2026-08-21: "grounded" ≠ "different"

Same 12 vignettes, criteria v2, `evals/reports/2026-08-21T062121Z` (off) /
`2026-08-21T062618Z` (on). Triage identical by design (RAG never touches
the decision). Reading the explanation texts side by side, **they are
paraphrases of each other** — the manual passages sit in the prompt
(`grounded=True` means injected, not used) and change nothing the patient
hears. Reason: the uploaded document is the *triage-criteria* manual —
levels, vital thresholds, department tables — precisely the content the
patient-facing rules forbid saying, so the model has nothing from it it is
allowed to use. RAG over this document is nurse-facing provenance, not a
patient-text improvement; do not claim otherwise.

One real signal from the side-by-side: with RAG **off** the English model
invented wayfinding in 3 of 4 non-emergency replies ("just down the hall to
your left") vs 1 of 4 with RAG on (n too small to matter). That is a
hallucination independent of RAG — the map card gives the real route — and
needs a prompt rule / validator check, not more retrieval. Content that
*would* change patient text is patient-facing material (clinic location,
hours, what to bring, preparation), which is a different upload.

### Extraction prompt: language-filtered catalog + static-first order (2026-08-21)

Before: 20.3k chars on turn 1 (131 catalog lines, bilingual labels + mixed
synonyms), 15.5k on later turns; the per-turn context sat *before* the
catalog, so a prefix-caching server re-prefilled everything every turn.
After: labels/synonyms in the session language only (ids unchanged), and
instructions → categories → catalog → rules → *then* context + message.
Sizes: th turn 1 12.8k, later 10.1k; en 13.7k / 10.9k (−35%). The catalog
membership is untouched — every level-1/2 finding is still always offered
(the 30/60 lesson from 2026-08-05).

`run_extraction_eval.py`, 71 phrases, Gemini, same day, same model:
**70/71 before, 70/71 after**, identical failure and identical strays
(interim reports not retained; the final run below is). The one failure
(`syncope_th_1`, "วูบหมดสติไปแป๊บนึง" → `loc_transient`) was structural, not
the prompt: `syncope_24h` and `loc_transient` listed the *same* synonyms
(`วูบหมดสติ`, `blacked out`), a coin-flip by construction. Criteria v3
separates them — `loc_transient` is now "only when a head injury / blow
caused it" with injury-anchored synonyms; `syncope_24h` gains วูบ / หน้ามืด /
fainted / collapsed. **71/71** after
(`evals/reports/extraction-20260821T091820Z.json`), incl. the head-injury
case still landing on `loc_transient`.
Per-language *models* were considered and rejected: a Thai-capable model
(Typhoon/Qwen) handles English, and two models double GPU memory for
nothing.

### Natural-language probe (2026-08-21)

`scripts/probe_natural_language.py` — 14 phrasings absent from the catalog
(Thai slang, Northern dialect "ปวดต๊อง ปวดฮิมสะดือขวา", a parent describing an
infant, rambling, code-switched "มี fever… เริ่ม rash"). Gemini mapped 14/14 to
the intended finding ids incl. the negations. Two things to watch: a
lethargic infant ("ซึมๆ ไม่ค่อยดูดนม") became `confusion` (right escalation,
imprecise word — candidate `lethargic_infant` finding), and "shivering" was
inferred as `fever` (an inference; harmless because fever is not level-1/2
and those get confirm-before-fire). Re-run on the local model before go-live.

### Demo plan + the echoed red-flag question (2026-08-21)

`docs/demo-test-plan.md` fixes five scripted patients (ids in the headings)
with the rule each must fire; all five passed live
(`evals/reports/2026-08-21T111203Z.md`). Preparing it exposed an echo:
`uq_breathing` (dyspnea + severe_respiratory_distress) was asked a second
time, verbatim, after the patient had answered it "yes". The red-flag
"resolved only when every finding is known" rule now has one exception —
a question that was *asked* and came back with one of its findings present
is answered; the severity grade is for the follow-on scale/measurement.
Volunteered-before-asking still asks once (the wound-infection case).
Re-run: `uq_breathing → uq_gender → uq_spo2 → L1`, 4 turns.

What changed since the 2026-08-12 measurement above:

1. The `\byou have\b` validator rule now ignores empathic recaps ("you have
   been experiencing / told me / mentioned …"). The EN template-fallback
   regression (5/25 → 15/25 with RAG) is gone: 0 fallbacks in both arms.
2. The explain node consumes `search_triage_manual_status` and injects
   passages only when `available`; the old path pasted the Thai "manual
   unavailable" sentence into the prompt as guidance. Every explain audit
   entry now carries `rag: {used, reason, hits[{title,page,chars}], chars,
   latency_ms}` → `ai_inference_audit.rules_trace` → `/admin/sessions/{id}/trace`,
   the nurse review ("อธิบายอิงคู่มือ หน้า N" / "ไม่ได้อิงคู่มือ — เหตุผล") and
   `GET /admin/ai-metrics.grounding`. "With vs without the upload" is now a
   number, not a belief.
3. Every question is rendered by one structured call (`ack` + question +
   options) with the persona (`app/data/persona_default.json`) and the last
   two exchanges in the prompt; red-flag/scale/measurement/confirm text
   stays verbatim by construction. `--rag` in `run_triage_eval.py` now reports
   grounded and template-fallback counts per arm, and vignettes may carry
   `utterances`, `must_not_ask`, `department_name_*` and `oracle`.
4. Offline, the present-aware feeder (`present_feeder`) drives 19 smoke
   vignettes through the real engine in `tests/screening/test_e2e_vignettes.py`
   (0 undertriage, 0 leaks, 100% oracle agreement) on every test run; the live
   counterpart is `tests/screening/test_e2e_vignettes_live.py` (integration).

Conclusion: `--rag` is safe to leave on for the explain node. Its value is
still bounded by what the uploaded manual contains; the grounding rate on the
admin metrics card is the thing to watch after each manual upload.

## Measured: mid-interview corrections (2026-08-22)

Question asked: when the patient restates mid-interview — "พูดผิด ไม่ได้ปวดท้อง
แต่เจ็บแน่นหน้าอก", "I meant 4 not 7", "that was my mother's fall" — does the
engine follow? Six scripted corrections through the real engine (Gemini,
criteria v3), state inspected after every turn:

| Correction | Before |
|---|---|
| B "sweating" → "actually not sweating" (pre-dispose) | ✅ finding flipped, confirm skipped |
| D pain "7" → "I meant 4" | ✅ `pain_score` 4 … ❌ `slots.severity` kept "it's like a 7" (nurse summary, SBAR) |
| E "2 days, 65" → "a week, 56" | ✅ |
| A "ปวดท้อง" → "พูดผิด … เจ็บแน่นหน้าอก" | ❌ findings right, but `complaint_category` stayed abdominal_pain and `chief_complaint` stayed "ปวดท้อง" — the emergency reply said *"เข้าใจแล้วค่ะว่ามีอาการปวดท้อง…"*; `symptoms_summary` (nurse queue, SBAR, surveillance) carried the retracted complaint |
| F fever, then "แน่นหน้าอกด้วย" | ❌ `chest_pain` recorded, then ignored — only the fever template's questions were ever eligible |
| C L2 declared, then "พูดผิด ไม่ได้เจ็บหน้าอก" | ❌ dropped: `REPEAT_GUIDANCE`, not even recorded |

The engine was already a belief state (findings/slots/vitals/age re-merged
every turn, rules re-decide from scratch) — and the raw extraction call already
returned each correction (old finding absent, new one present, chief complaint
restated, new category). Four write-once spots discarded it. Fixed without a
new LLM call:

1. **Category re-route on evidence.** Templates now carry `anchor_finding_ids`
   (the finding that *is* the complaint; criteria v4). `ingest._apply` moves a
   specific category to another specific one only when every anchor of the
   current one was retracted this turn, or the chief complaint was restated
   *and* the new complaint's anchor is present. The model's category pick
   alone never moves it (it re-picks every turn). Old complaints go to
   `state.complaint_history`.
2. **Second complaint.** `question_policy` slots the red-flag questions of any
   other template whose anchor is present — and which the session template
   does not already account for (its associated symptoms or anything its own
   questions check) — right after the session template's own red flags (red
   flags only — the budget stays the cap). Completeness holds for them too.
   The "already accounted for" clause came from the regression run: without
   it a febrile UTI (`ur_th_flank_fever`) drew the whole fever screen on top
   of the urinary one and spent the 12-question budget before its own slots,
   level 3 → 4.
3. **`slots.severity` follows the score** (assignment, not `setdefault`).
4. **Post-disposition: record, never re-triage.** The repeat node keeps
   anything said after the disposition in `patient_follow_up` (→ nurse review,
   SBAR documentation) and says so; wayfinding questions still get the
   guidance. The level is the nurse's to change.
5. **Confirm-before-stand-down.** A *confirmed* critical finding retracted in
   free text (not as the answer to its own question) gets its verbatim confirm
   once before the rule stands down — the mirror of confirm-before-fire, so an
   STT "ไม่" cannot cancel an emergency path silently. Same two-ask cap.
6. Extraction prompt: one rule for "was a mistake / has gone / was about
   someone else → absent", `chief_complaint` defined as first message or an
   explicit replacement (never a mere addition); every template's anchors are
   always in the catalog so a replaced complaint can be named from inside an
   unrelated template.

**Extraction eval** (`evals/extraction_phrases.json`, now 81 cases: +10
`corr_*` mid-interview cases with preset state and `expect_chief_complaint`
true/false): 71/71 → **81/81** (`evals/reports/extraction-20260822T095610Z.json`).
A trap on the way: lengthening the `chief_complaint` *schema description*
("…or when they explicitly correct/replace their main problem…") flipped
gemini-3.1-flash-lite's turn-1 pick for epigastric pain — `abdominal_pain` →
`gi` 4/4 in both languages, and "จุกลิ้นปี่" → `chest_pain` — with the prompt
otherwise identical; the same semantics as a prompt rule had no such effect.
The description is back to its one-line original and the rule carries the
meaning. Lesson for the local model too: field descriptions are prompt, and
the eval must run after touching them.
Before the prompt rule, "ปวดหัวคือเมื่ออาทิตย์ก่อน หายแล้ว" left `headache`
present; "that was my mother's fall" could not name `sore_throat` (not in the
injury template's vocabulary) — both fixed. The model still rarely flips the
*old* anchor on a wholesale replacement; the restated-complaint signal covers
that path, so it is allowed, not scored.

**Live re-run of the probes** (same scripts): A → category chest_pain,
emergency reply *"เข้าใจแล้วค่ะว่ามีอาการเจ็บแน่นหน้าอก…"*, summary without
ปวดท้อง; F → `fv_danger, fv_chemo, fv_rash, cp_radiating, cp_diaphoresis`,
category fever; C → *"รับทราบค่ะ ดิฉันแจ้งเจ้าหน้าที่ไว้ให้แล้ว…"*, text in
`patient_follow_up`, level untouched; B2 (chip-tap yes to sweating, then
"เมื่อกี้พูดผิด เหงื่อไม่ได้ออก") → one `confirm_diaphoresis`, "ไม่มีค่ะ" →
absent-confirmed, interview continues, no L2. One residual echo: after the
retraction confirm, `cp_diaphoresis` is asked once more because its second
finding (`pale_cold_sweaty`) is still unknown — the compound-red-flag rule,
one extra turn, safe.

Still write-once by decision: a device reading (speech never overrides the
cuff/thermometer/oximeter; re-measure is the card's "วัดใหม่" before confirm),
an HIS-recorded gender, and the disposition itself.

Offline: `tests/screening/test_corrections.py` replays the probes' extractions
through the engine with the fake model.

**Vignette regression** (75, live, RAG on, `evals/reports/2026-08-22T102246Z.md`):
61/75 passed, **undertriage 0/22**, level exact 94.7 % (2026-08-12 baseline on
65: 90.8 %), within-1 100 %, category 93.3 %, department 94.7 %, 0 validator
leaks, 0 explain fallbacks, avg 8.3 turns. 12 of the 14 failures are the same
vignettes that failed on 2026-08-12 (the demo five pass). The two that are
new — `ap_th_dyspepsia`, `inj_en_ankle` — plus `gen_th_anaphylaxis` (which
swapped one wrong category for another) are all turn-1 model picks
(`gi` for ลิ้นปี่, `musculoskeletal` for a rolled ankle, `nose_throat` for lip
swelling + throat tightness), reproduced 3/3 with the *original* prompt as
well; level and department are right in each. Nothing in this change moves a
category on turn 1 — the switch logic needs a prior category and evidence —
so these are the model's, not the engine's. The first full run
(`2026-08-22T091354Z`, 60/75) is kept as the before-narrowing evidence for
`ur_th_flank_fever`.

## Measured: natural wording for every question, guarded (2026-08-23)

Complaint: the interview still read like a form — about half the lines were
templates (every red flag, scale, measurement and confirm), and the confirm
questions were catalog *labels* in a sentence ("do you have this right now:
Chest pain / tightness?").

Change, without a new model call or a judge: the render call may now reword
every kind except a measurement request, and a rewording is used only when a
deterministic guard (`nodes/question.wording_violations`) finds nothing to
object to:

- it still names every symptom the template names — English by 4-char stems
  of the finding's label/synonym words, Thai by label/synonym "cores" with
  substring / 70 %-contiguous / two-piece matching (Thai inserts words
  mid-phrase: "ถ่ายดำ" ↔ "ถ่ายอุจจาระเป็นสีดำ"); marks shared with a sibling
  finding or pure context ("fever" in "stiff neck with fever") never count;
- a yes/no question stays yes/no (no "แค่ไหน / which / how");
- a scale keeps 0 and 10; exactly one question; bounded length; validator.

Otherwise the template goes out and the audit records `paraphrase_rejected`.
The prompt tells the model which words to keep (severity-grade siblings
excluded). Chips stay id-mapped for red-flag/scale/confirm, so wording can
lose a symptom but never change what a tap means. The 86 critical findings
got authored confirm sentences (`confirm_en/th`, criteria v5) so even the
fallback reads like a person; measurement lines were reworded.

Tuning was done against the real model's rewordings
(`scripts/review_question_wording.py`, 470 renders per run). Holes found and
closed on the way, all of which a looser check accepted: Thai bigram overlap
let "อาเจียนเป็นเลือด" cover the dropped "ถ่ายเป็นเลือด"; English all-stems
let a template that paraphrases a finding loosely leave it unguarded ("how
were you stabbed?" for the injury-mechanism question); a keep-line that listed
the severe grade made "trouble breathing?" become "severe trouble breathing,
can't speak in full sentences?" (a mildly breathless patient would answer
no and skip the oximeter); a Thai confirm became a degree question
("ยังแน่นหน้าอกอยู่มากน้อยแค่ไหนคะ"). Each is now a test in
`tests/screening/test_wording_guard.py`.

Result (`evals/reports/question-wording-20260822T183728Z.md`, Gemini):
**th 225/235 rewordings used, en 220/235**; every refusal is a dropped
symptom, a wh-question, two questions, or a validator hit — the template then
goes out. Demo scenarios ×2 languages live after the change
(`2026-08-22T184028Z.md`): 9/9 pass, 0 leaks, e.g. *"Are you feeling that
tightness in your chest right now?"* / *"ตอนนี้ยังมีเหงื่อออกมากหรือเหงื่อแตกอยู่ไหมคะ"*
instead of the label sentences.

What a nurse signs off on is the policy ("the model may reword; it must name
the symptom and stay yes/no") plus the sheet — not every sentence. Re-run the
sheet on Typhoon before go-live; Thai wording is where a small local model
will show first.
