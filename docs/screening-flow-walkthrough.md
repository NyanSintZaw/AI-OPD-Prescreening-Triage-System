# One patient through the engine — speech → ids → rules → reply

A worked example of exactly what happens on each turn, with the real artifacts
(prompt fragments, the model's JSON, the rule that fired, the rows written).
Demo scenario 1 from `docs/demo-test-plan.md`: chest pain with sweating,
Thai, seeded HN 09900001 (สมชาย, male, 41). Recorded 2026-08-22 against
criteria v4, gemini-3.1-flash-lite; the same bodies go to the local model
when `SCREENING_MODEL_PROVIDER=openai_compatible` (see `docs/ai-model-io.md`
and Postman *AI Model (local inference)*).

The one rule that explains everything below: **the LLM maps words onto a
fixed vocabulary of ids; pure Python decides what the ids mean.** Three model
calls happen in this journey. Only the first can change the triage, and it can
only say *which catalog ids the patient affirmed or denied*.

## What the model knows about the criteria — and what it never sees

| Criteria piece | Sent to the model? | How |
|---|---|---|
| Category ids (24: `chest_pain`, `fever`, …) | yes | one line in the extraction prompt: *Allowed complaint categories (copy ONE id verbatim): …* |
| Finding catalog — id, label, ≤ 6 synonyms, **session language only** | yes, a bounded subset | the *Finding catalog (use ONLY these ids)* block. Turn 1: every finding any template asks about (~90). Later turns: the active template's findings + every finding an L1/L2 rule references + every template's anchor (~50). The JSON schema then forces `finding_updates[].id` to be a string; ingest drops any id not in the catalog |
| Question texts | yes, one at a time | the pending question is pasted into the extraction `Context:` with the ids it checks, so a bare yes/no maps mechanically; the question node gets the one selected question to acknowledge/paraphrase |
| Template `keywords_th/en` | **no** | used only by the deterministic keyword net in ingest when the model returns no/generic category |
| Rules — level-1 criteria, tuples, danger vitals, routing table, fast tracks, citations | **no** | pure Python in `rules/` over the findings dict |
| Vital bounds, age bands | no | `vitals.check_vitals`, rules |

The catalog is derived from the criteria at prompt-build time, so a new finding
or synonym published in the Rule Book reaches the model on the next turn
without a prompt edit — and `scripts/run_extraction_eval.py` is the check to
run after touching synonyms, the prompt, **or a field description in the
schema** (measured 2026-08-22: a longer `chief_complaint` description alone
flipped a turn-1 category; see `docs/ai-quality-evaluation.md`).

## Turn 1

**Patient (voice):** “แน่นหน้าอกเหมือนช้างเหยียบเลยค่ะ เหงื่อแตกท่วมตัว”

1. **STT** (`google_stt.py`, or the local `openai_compatible` STT) → that text.
   `TriageService` calls `engine.run_turn(session_id, "th", content,
   turn_context={"age_years": 41, "gender": "male", "vitals": {}})` — HIS
   age/gender and any device readings are merged into state **before** the
   graph runs (`engine._apply_turn_context`), so a cuff reading of 200/120
   can dispose on turn 1 without the model.

2. **ingest → model call #1, extraction** (`nodes/ingest.py`,
   `extraction.build_extraction_prompt`). Prompt = instructions → category
   list → catalog → rules → `Context: This is the first message.` → the
   message. Two of the ~90 catalog lines:

   ```
   - chest_pain: เจ็บแน่นหน้าอก (also: แน่นหน้าอก, จุกอก, …)
   - diaphoresis: เหงื่อออกมาก เหงื่อแตก (also: เหงื่อแตกท่วมตัว)
   ```

   Schema-constrained reply (`response_format: json_schema`; what Gemini
   actually returned):

   ```json
   {"chief_complaint": "แน่นหน้าอก",
    "complaint_category": "chest_pain",
    "finding_updates": [
      {"id": "chest_pain",  "state": "present", "evidence": "แน่นหน้าอกเหมือนช้างเหยียบ"},
      {"id": "diaphoresis", "state": "present", "evidence": "เหงื่อแตกท่วมตัว"}
    ],
    "slot_updates": {}, "age_years": null, "gender": null,
    "pain_score": null, "distress_score": null,
    "is_question_to_assistant": false, "wants_human": false}
   ```

   `_apply` merges it: `state.findings = {chest_pain: present, diaphoresis:
   present}` — both **unconfirmed** (free text), each with its `evidence`
   quote checked for literal presence in the utterance (the nurse-trace
   flag); `complaint_category = "chest_pain"`, `chief_complaint = "แน่นหน้าอก"`.
   Audit row: `call_site=extraction, extracted={…}, latency_ms`.

3. **Red-flag gate** (`graph.route_after_ingest` → `rules.disposition.decide`,
   pure). The criteria tuple matches:

   ```
   tt_chest_pain_diaphoresis
     findings_all: [chest_pain, diaphoresis]   → force_min_level: 2
     citation: MOPH ED Triage; ESI v5 ch.4 (decision point B); MFU Chest Pain Checklist
   ```

   Provisional level **2**. **Confirm-before-fire:** the gate re-runs on
   *confirmed* findings only → nothing fires → no disposition yet;
   `state.pending_confirm = [chest_pain, diaphoresis]`.

4. **question node → model call #2, render** (`nodes/question.py`). The pick
   is deterministic: `confirm_question_for(chest_pain)` — the catalog's
   authored confirm sentence (“ขอถามให้ชัดนะคะ ตอนนี้เจ็บหรือแน่นหน้าอกอยู่ไหมคะ”).
   The model returns a short `ack` and a rewording; the rewording is used
   only if `wording_violations` is empty (it still names chest pain, stays
   yes/no, one question, no leaks) — otherwise the authored sentence goes
   out. `validate_reply` checks the whole reply in Thai and English.

   **Booth:** “เข้าใจแล้วค่ะ ตอนนี้อาการเจ็บแน่นหน้าอกของคุณยังคงมีอยู่ไหมคะ” → TTS.
   `pending_question_id = confirm_chest_pain`; chips: ใช่ / ไม่ใช่.

## Turn 2

**Patient:** “ใช่ค่ะ”

- Extraction context now carries *The assistant just asked: … That question
  checks exactly these finding ids: chest_pain* → `{"id": "chest_pain",
  "state": "present"}`. Because it answers its **own** question, ingest sets
  `chest_pain.confirmed = True`.
- Gate on confirmed findings: still no rule (diaphoresis unconfirmed) →
  `confirm_diaphoresis` is asked (“ตอนนี้ยังมีเหงื่อออกมากหรือเหงื่อแตกอยู่ไหมคะ”).

## Turn 3

**Patient:** “ใช่ค่ะ” → `diaphoresis.confirmed = True`.

- Gate on confirmed findings: `tt_chest_pain_diaphoresis` fires → level 2 →
  `is_interview_complete` is true immediately (level ≤ 2 never waits for
  OLDCARTS or measurements).
- **dispose** (`nodes/dispose.py`, pure): level 2 → department forced to
  **emergency**. (The routing row `chest_pain → opd_cardiology` is what a
  level-3+ chest-pain patient would get — OPD-first applies to levels 3–5
  only.) Writes:

  ```
  classification = {level: 2, color: …, department_code: "emergency",
                    red_flags: ["tt_chest_pain_diaphoresis"],
                    disposition_reasons: [{rule_id, text_th: "เจ็บแน่นหน้าอกร่วมกับเหงื่อแตก (สงสัยหัวใจขาดเลือด)",
                                           citation: "MOPH ED Triage …; MFU Chest Pain Checklist"}],
                    symptoms_summary: "แน่นหน้าอก"}
  ```

  Audit row: `call_site=disposition, level=2, fired_rules=[…]`.
- **explain → model call #3** (`nodes/explain.py`). The prompt gets *only*:
  persona, `symptoms_summary`, the department's display name, the urgency
  line, a `[NAME]` placeholder — **no level, no rule, no RAG** (emergency
  explanations never use the manual). Reply validated; the real name
  substituted in afterwards.

  **Booth:** “…รบกวนให้รีบไปที่ห้องฉุกเฉินทันทีเลยค่ะ เจ้าหน้าที่ได้รับแจ้งเรื่องของคุณแล้ว…”
  `phase = disposed`, `flow_complete = true`.
- **TriageService** persists the engine's decision verbatim: `symptom_entries`,
  `severity_assessments` (level 2), `department_recommendations`
  (emergency), `assessment_reviews` (nurse queue: level, reasons with
  citations, evidence quotes, vitals with device tags), `disease_surveillance`.
  The patient payload redacts the level to `"unknown"`
  (`triage_payloads.py`).

Anything the patient says after this (“เดี๋ยวค่ะ พูดผิด…”) is recorded into
`patient_follow_up` for the nurse and SBAR, and is **not** re-triaged.

## Where each hop lives

| Hop | Code | Proof |
|---|---|---|
| Objective inputs before the graph | `engine._apply_turn_context` | `tests/screening/test_engine.py` |
| Extraction prompt / schema | `extraction.py`, `nodes/ingest.py` | `run_extraction_eval.py` (81 cases), `test_no_pii_in_prompts.py` |
| Merge + corrections | `ingest._apply`, `_apply_category` | `test_ingest_category.py`, `test_corrections.py` |
| Red-flag + completeness gates | `graph.route_after_ingest`, `rules/red_flags.py`, `rules/disposition.py`, `rules/question_policy.py` | table-driven `test_red_flags.py`, `test_disposition.py`, `test_question_policy.py` |
| Question pick / render | `rules/question_policy.next_question`, `nodes/question.py` | `test_question_ack.py`, golden transcripts |
| Dispose / department | `nodes/dispose.py`, `rules/department_map.py` | `test_engine_authority.py` |
| Explain | `nodes/explain.py`, `validator.py` | `test_validator.py`, `test_explain_rag.py` |
| Persistence | `services/triage_service.py` | `test_engine_authority.py` (engine decision persisted verbatim) |
| Audit | `ai_inference_audit` → `GET /admin/sessions/{id}/trace` | — |

A non-emergency journey differs only in the middle: after the red flags the
policy walks the template's scale/measurement/OLDCARTS questions (device
cards pop for `measurement` kinds), disposes at level 3–5 through the routing
table (OPD-first), and the explain call may cite the uploaded manual (RAG,
non-decisional) before offering the follow-up note.
