# Vital plausibility bounds

Every number that enters the screening engine — spoken, typed, or reported by
the blood-pressure cuff — is first checked against a **plausibility bound**. A
value outside its bound is discarded before any triage rule can see it, and the
patient is asked for it again.

The bounds live in the versioned criteria document (`vital_bounds` /
`cross_checks`), so a head nurse can retune them through the normal criteria
upload → review → activate lifecycle without a code change.

---

## The one rule that matters

**"Impossible" and "dangerous" are different axes. Never merge them.**

| Reading | Plausible? | Dangerous? | What happens |
|---|---|---|---|
| `250/130` | yes | yes | Accepted, fires `dv_adult_bp_crisis` → level 2, emergency |
| `400/220` | **no** | — | Discarded. No rule sees it. No rest window. Re-measure |
| `118/76` | yes | no | Accepted, normal |

Bounds are an **input filter**, never a triage threshold. If a bound were
tightened to the point where a real hypertensive crisis (or a real fever) fell
outside it, the system would silently stop detecting that emergency. That is
why the bounds are deliberately far wider than any clinical band, and why
`test_criteria_v2.py` pins that `250/140` still fits inside them.

---

## The bounds

| Vital | Range | Unit | Notes |
|---|---|---|---|
| `sbp` | 50 – 300 | mmHg | Systolic |
| `dbp` | 20 – 200 | mmHg | Diastolic |
| `hr` | 20 – 250 | bpm | Pulse |
| `rr` | 4 – 80 | /min | Respiratory rate |
| `spo2` | 50 – 100 | % | |
| `temp` | 30 – 45 | °C | Below 30 °C is incompatible with a conscious walk-in |
| `weight` | 1 – 400 | kg | |
| `height` | 30 – 272 | cm | |
| `age_years` | 0 – 120 | years | Bounded when spoken; HIS ages bypass the interview |
| `pain_score` | 0 – 10 | — | Also enforced by the extraction schema |
| `distress_score` | 0 – 10 | — | Also enforced by the extraction schema |

Bounds are **inclusive** at both ends.

### Cross-field checks

Some values are individually valid but impossible together. The logic is in
code (it compares two vitals, which the per-vital table cannot express); the
patient-facing wording is in the criteria under `cross_checks`.

| Check | Rule | Catches |
|---|---|---|
| `sbp_le_dbp` | systolic must exceed diastolic | Swapped entry (`80/120`) |
| `bmi_implausible` | implied BMI must be 5 – 150 | Unit mix-ups (height typed in metres, weight in pounds) |

### Blood pressure is one measurement, not two numbers

If **either** half of a BP reading fails its bound, **both** are discarded. A
cuff cycle that produced an impossible diastolic did not produce a trustworthy
systolic either. Without this, `300/220` would leave `sbp = 300` standing and
fire the hypertensive-crisis rule off a reading that never happened.

The derived mean arterial pressure (`map`) is dropped along with them.

---

## Where the check runs

One function — `check_vitals()` in
`app/services/screening/vitals.py` — is the only gate, called from every rail:

| Rail | Entry point | On rejection |
|---|---|---|
| Cuff / HIS / kiosk form | `engine._apply_turn_context` | Value never reaches the red-flag gate |
| Spoken or typed in chat | `nodes/ingest._apply` | Value never reaches `state.vitals` |
| Cuff parser | `blood_pressure._parse_result_json` | Record skipped like a malformed one; status `implausible` |
| REST write path | `SessionVitalsUpdate` / `SessionMeasurementUpdate` | `422`, so it never reaches session metadata (and so never the HIS) |
| Kiosk UI | `MeasurementCard`, bounds from `GET /screening/vital-bounds` | Inline message, nothing submitted |

A rejected vital is simply **absent** from the accepted map, and
`rules/evaluator.py` already guarantees that a missing vital never satisfies a
rule leaf. So an impossible value is inert by construction rather than by a
second guard remembering to check.

---

## What the patient sees

### Typed or spoken values — two tries, then move on

1. The value is refused and the measurement question is asked again, led by the
   nurse-approved `retry_text` for that bound (verbatim, never LLM-paraphrased),
   so the patient learns *what* was wrong rather than seeing the same question.
2. If the second attempt is also impossible, the engine gives up on that vital
   and continues. The interview must always terminate — a patient typing
   nonsense, or a voice call mishearing repeatedly, can never loop it.

This reuses the retry mechanism red-flag questions already had
(`_ask_count(...) >= 2` in `rules/question_policy.py`); measurements were
previously resolved permanently after a single ask, so a lost value was lost
for the whole session.

### The cuff — measure again, immediately

An implausible cuff reading returns status `implausible` and the kiosk asks for
an immediate re-measure.

**It does not open the 15-minute rest window.** That window exists for a
genuine hypertensive crisis (`> 180 / > 110`), where the point is to let the
patient rest before a confirmatory reading. An impossible reading is not a
crisis reading — it is not a reading at all — so making the patient wait 15
minutes for it would be both pointless and alarming.

---

## What the nurse sees

A rejected vital is **shown flagged with the reported value, never blank**.

> ⚠ ~~50~~ reported by patient, outside the possible range

A blank `—` would read as "not measured", which is a very different clinical
signal from "the patient told us 50 °C". The nurse needs to know a value was
offered and refused — it may indicate confusion, a language problem, or a
broken instrument.

Two distinct fields on the review payload:

- `missing_vitals` — core vitals never instrument-measured (undertriage caution)
- `rejected_vitals` — values reported but refused, with `{value, reason, source, attempts}`

**Rejected values are never published to the HIS.** Stage 1 publishes
`metadata["vitals"]`; refused values are kept on the engine state
(`screening_sessions.state`) and refused at the REST write path, so they cannot
reach the hospital record as measurements. `tests/screening/test_vital_bounds.py`
pins this.

---

## Changing the bounds

The bounds are data, not code. `default_vital_bounds()` in
`app/services/screening/rules/criteria_models.py` supplies them to any criteria
document that doesn't author its own (so v1, still the active version, gets a
working filter without being rewritten); `screening_criteria_v2.json` authors
them explicitly with nurse-worded Thai and English.

To retune them, edit `vital_bounds` in the criteria document and take it
through the usual draft → review → approve → activate flow. Bound changes show
up in the admin review diff (`diff_criteria` includes the section). The whole
document is one JSONB column, so **no database migration is involved**.

If you change a bound, check it still admits the readings the danger-vital
rules are meant to catch — that is what `test_criteria_v2.py` and
`test_guardrail_precedence.py` verify.
