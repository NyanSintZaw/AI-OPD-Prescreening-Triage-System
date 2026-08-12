# Triage-quality eval harness

On-demand, real-LLM evaluation of the screening engine against labeled patient
vignettes. Drives `ScreeningTriageEngine` **directly** (no HTTP, no Postgres —
state lives in `InMemoryStateStore`, criteria come from the bundled seed) and
scores triage level, category, department routing, undertriage, question
coverage, and patient-facing safety leaks.

**Coverage claims about triage quality come only from reports produced by this
harness.** No report in `evals/reports/` for a change = no quality claim for it.

## Running

```bash
# prove the machinery, zero API spend (fake model; scores are plumbing checks only)
uv run python scripts/run_triage_eval.py --dry-run

# the real thing — uses the production model config from .env (API spend!)
uv run python scripts/run_triage_eval.py

# subsets
uv run python scripts/run_triage_eval.py --language th
uv run python scripts/run_triage_eval.py --ids cp_th_crushing,fv_th_infant

# score against the DB-active criteria version (needs DATABASE_URL; criteria
# are fetched once read-only, session state still stays in memory)
uv run python scripts/run_triage_eval.py --criteria active
```

Output: console summary + `evals/reports/<UTC-timestamp>.md` and `.json`
(aggregates first, then per-vignette rows with fail reasons and the full
transcript in the JSON).

The default run builds the model exactly like production
(`build_chat_model(settings)`), so `.env` must carry working Vertex/openai-
compatible credentials. RAG is disabled in the harness (it grounds
explanations only, never decisions).

## Vignette schema (`evals/vignettes.json`)

```jsonc
{
  "id": "cp_th_crushing",            // unique, snake_case
  "language": "th",                  // th | en — phrasing must be natural spoken language
  "description": "why this vignette exists",
  "opening": "แน่นหน้าอกเหมือนช้างเหยียบ...",   // the patient's first message
  "present": ["chest_pain", "diaphoresis"],  // findings that are TRUE for this
                                      // patient — REQUIRED (may be []). Answers
                                      // the confirm-before-fire questions, whose
                                      // synthesized ids match no regex. Only
                                      // list what the vignette actually supports.
  "age": 60,                          // injected as turn_context age (booth/HIS prefill)
  "initial_vitals": {"temp": 37.9},  // optional: booth vitals present from turn 1
  "answers": [                        // adaptive script: first regex match wins
    {"match": "cp_radiating",        // regex, tried against the pending QUESTION ID
     "reply": "ร้าวไปแขนซ้ายค่ะ"}    //   first, then against the question text
  ],
  "measurements": {"bp": [200,120], "temp": 38.4, "weight": 65, "height": 165},
                                      // injected as turn_context when the engine
                                      // asks a measurement (awaiting_measurement);
                                      // unlisted vitals get normal defaults
  "follow_up_reply": "ไม่มีแล้วค่ะ ขอบคุณค่ะ",  // optional post-disposition answer
  "follow_up_expected": "decline",   // optional: decline must close the flow and
                                      // must NOT be recorded as a patient note
  "expected": {
    "category": "chest_pain",        // string or list of acceptable ids
    "category_v2": ["palpitations"], // optional, preferred when present: the more
                                      // specific label (key name is historical —
                                      // added while a richer "v2" document
                                      // coexisted with the original seed)
    "level": [1, 2],                 // exact int or [min, max] band
    "department": "emergency",       // string or list of acceptable codes
    "undertriage_critical": true,    // true whenever expected level <= 2
    "must_ask": ["cp_radiating"],    // regexes over asked question ids / texts
    "must_not_leak": true,           // always true; validator runs on every reply
    "findings": {"fever": "present"},        // optional final-state checks
                                              // (present | absent | not_absent)
    "turn1_findings": {"fever": "absent"}    // optional turn-1 extraction checks
  }
}
```

Answer matching prefers **question ids** (stable across LLM paraphrasing);
text regexes are a fallback. Unmatched questions get a default "no"
(scale questions get a "3"), **except confirm-before-fire questions**: those
are answered "yes" iff the finding being confirmed is in `present`, so the
simulated patient neither denies its own opening (manufactured undertriage)
nor claims a finding it never had (manufactured overtriage). A vignette with
no `present` key at all gets a fail-safe "yes" plus a
`NO_PRESENT_FOR_CONFIRM:<finding>` entry in the run's unmatched list — never a
silent guess. The driver caps every vignette at 15 turns.

### Adding a vignette

1. Pick the id prefix from the category (`cp_`, `dc_`, `fv_`, `hd_`, `ap_`,
   `ear_`, `nt_`, `eye_`, `inj_`, `pg_`, `mh_`, `msk_`, `ur_`, `gen_`).
2. Write the opening in natural colloquial language — spoken Thai with polite
   particles, casual English. Never clinical phrasing; the whole point is
   testing extraction from how patients actually talk.
3. Label `expected` with the **clinically correct** answer, not what the
   engine currently does. When a more specific label exists (e.g.
   `palpitations`), put it in `category_v2` (historical key name) — the
   harness prefers it whenever present.
4. Give answers for every red-flag question of the category plus onset /
   duration / character / severity, so real-model runs never stall on defaults.
5. `uv run pytest tests/screening/test_eval_driver.py` — schema is validated.

## Metrics

| Metric | Definition |
|---|---|
| **Undertriage rate** | Of vignettes with expected level ≤ 2, the share assessed > 2 (or never disposed). Every miss is a CRITICAL fail — this is the headline safety number. |
| Undertriage 95% CI | Clopper-Pearson **exact** binomial CI on the undertriage rate (pure-python regularized incomplete beta, no scipy). Reported so small-n rates aren't over-read. |
| QWK | Quadratic-weighted Cohen's kappa over (expected, assessed) level pairs, 5 classes. **Band convention:** for a banded expectation `[lo, hi]`, the "expected" value in the pair is the assessed level clamped into the band — an in-band assessment scores perfect agreement; an out-of-band one is penalised only by its quadratic distance to the nearest band edge. Unclassified vignettes are excluded from QWK (they still count as undertriage/level fails). |
| Level exact | Assessed level inside the expected band (an exact int label is a width-1 band). |
| Level within 1 | Assessed level within band ± 1. |
| Category match | Final `complaint_category` in the accepted list (`category_v2` preferred when present). |
| Department match | Disposed `department_code` in the accepted list. |
| Leak count | Total validator violations (`validate_reply`) across every patient-facing reply of every turn — must be 0. |
| must_ask coverage | Each listed pattern matched an asked question id or question text before disposal. |
| Pass | All of the above plus the vignette's finding / follow-up checks; any fail reason lists why. |

All headline metrics are also computed **per language (th / en)** as an equity
signal — a gap between the th and en blocks means extraction or phrasing
quality differs by language, which is itself a defect. The `by_language` block
appears in the console summary and in both report files.

Dry-run reports are **plumbing checks only** — the fake model seeds the
category and extracts nothing else, so clinical scores in a dry-run report are
meaningless and must never be quoted as coverage.

## External benchmark

Reports from this harness should be read against the published template of the
BIZUSIZO study (2026 preprint): 120 vignettes, under-triage 3.3%
[95% CI 0.9–8.3], QWK 0.891. It is a reporting *template* (metric set, CI
style, vignette count), not a pass/fail bar — but a real-model run whose
undertriage CI or QWK is far outside that neighbourhood warrants investigation
before any quality claim.
