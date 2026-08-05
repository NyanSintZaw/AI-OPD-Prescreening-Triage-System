# Screening Criteria — Source Standards & Provenance

This document states exactly which clinical standards the screening criteria are
based on, how each part of the criteria document maps to those standards, and how
per-rule citations work. It exists so that hospital staff, auditors, and patients'
representatives can verify that the AI kiosk's triage logic is not invented by the
vendor or the model — every rule traces to a published source.

## Primary standard: Thai MOPH ED Triage (5-level)

- **What it is:** Thailand's national five-level emergency triage guideline —
  แนวทางการคัดแยกผู้ป่วยฉุกเฉิน, กรมการแพทย์ กระทรวงสาธารณสุข (Department of
  Medical Services, Ministry of Public Health), 1st ed. 2561 (2018).
- **Official document:**
  <https://www.dms.go.th/backend/Content/Content_File/Population_Health/Attach/25621021104459AM_44.pdf?contentId=18326>
- **What it governs here:** the five levels, their colors, and the
  response-time targets are MOPH semantics. Everything the patient-facing and
  nurse-facing surfaces call "level 1–5" is the MOPH scale, not any foreign
  scale.

## Local operational source: MFU Medical Center OPD manual

The MFU manual (คู่มือเกณฑ์การคัดกรองผู้ป่วย) seeded criteria v1 and remains the
immediate source for Thai-specific wording, the hospital's department structure,
fast tracks (BEFAST, sepsis), and per-department level-2 lists. It is itself
written against the MOPH 5-level guideline.

## Internal design pattern (after ESI): decision-point structure

The rules engine's *internal* decision flow is organised as a sequence of
decision points, a structure patterned after the Emergency Severity Index
handbook (ESI, 5th ed. 2023, Emergency Nurses Association;
<https://media.emscimprovement.center/documents/Emergency_Severity_Index_Handbook.pdf>).
This is an unbranded design pattern plus factual content reference — **not an
ESI implementation**, and important limits apply:

- ESI is validated for **nurse-operated emergency-department triage**, not for
  OPD self-report kiosks. This system does not implement, and does not claim
  conformance to, ESI.
- ESI defines **no response times and no colors** — those are MOPH semantics.
- The ESI handbook is **copyrighted by the Emergency Nurses Association** with
  no public software license; we cite it for specific factual content only
  (e.g. Table 6-1/6-2 vital-sign thresholds, decision-B example presentations).
- The **resource band** (`disposition._resource_band`) and the **pain/distress
  escalation thresholds** are **local MFU heuristics**, not ESI content — ESI's
  actual resource count and pain handling are nurse-judgment steps we do not
  reproduce. They are validated via the on-demand eval harness and nurse
  re-routing review.

| Internal decision point (after ESI) | Our criteria section | Engine code |
|---|---|---|
| A — dying / immediate life-saving intervention | `level1_criteria` | `rules/red_flags.py` |
| B — high-risk situation, shouldn't wait | red-flag questions + `triage_tuples` → level 2 | `rules/red_flags.py`, `rules/disposition.py` |
| C — expected-resources band (local heuristic) | resource band (level 3/4/5) | `disposition._resource_band` |
| D — danger-zone vitals | `danger_vitals` | `rules/red_flags.py` + booth vitals via `turn_context` |
| Severe pain/distress escalation (local heuristic, threshold after ESI's ≥ 7 consideration) | pain/distress scale escalation | `disposition._scale_escalation` |

The booth-vitals rail (measured vitals merged into state before the red-flag
gate) ensures levels are never assigned on self-report alone when measurements
exist.

Every value on that rail first passes a **plausibility filter** (`vital_bounds`
in the criteria document) so an impossible reading — a slipped cuff reporting
300/220, a patient typing 50 °C — is discarded before any rule evaluates it,
and re-asked. Those bounds are an input filter, never a triage threshold: they
are deliberately wide enough that every danger-zone vital above remains
detectable. See [vital-bounds.md](vital-bounds.md).

## Breadth checklist: MTS presentation list (Manchester Triage System)

The MTS organises triage into ~52 **presentation-based** flowcharts ("headache",
"wounds", "palpitations"…) — the same shape as our `complaint_templates`. We use
the MTS presentation *list* as the coverage checklist that decides **which
complaint templates must exist** so real OPD walk-ins don't fall through to the
generic path.

**Copyright note:** MTS flowchart content (its discriminators) is copyrighted
(Emergency Triage, Mackway-Jones et al.). We do **not** copy MTS discriminators.
Question and red-flag content inside each template is authored from the Thai
MOPH ED Triage guideline, the MFU manual, factual content referenced from the
public ESI v5 handbook, and standard emergency-medicine references, each with
its own citation.

## The two layers of a criteria document

1. **Clinical base (standards-derived):** `finding_catalog`, `level1_criteria`,
   `danger_vitals`, `triage_tuples`, red-flag questions, fast tracks. Derived
   from MOPH ED Triage + the MFU manual (with specific factual references to the
   ESI v5 handbook where noted); carries citations; maintained in the versioned
   seed files (`app/data/screening_criteria_v*.json`).
2. **Hospital infrastructure (site-specific):** `routing_table`,
   `department_rules`, department codes/names. Each hospital adapts this layer to
   its own OPD structure through the criteria version lifecycle
   (draft → review → approve → activate) using the admin JSON editor.

There is **no document-upload/LLM-extraction path for screening criteria**
(removed July 2026): criteria are curated and reviewed, never machine-generated.
The separate *triage manual* upload (`/admin/triage-manual/upload`) only feeds the
RAG index that grounds patient-facing **explanation wording** — it was proven in
the July 2026 E2E evaluation to have zero influence on triage decisions.

## Per-rule citations

Every rule (level-1 criterion, danger vital, triage tuple, department rule, fast
track) and every red-flag question carries a `citation` string in the criteria
JSON, rendered in the admin criteria viewer and in nurse-facing
`disposition_reasons`. Formats — MOPH leads:

- `"MOPH ED Triage (5-level), <section>"` — the governing standard
- `"MOPH ED Triage (5-level); ESI v5 Handbook, ch. <n> (<topic>)"` — rules whose
  specific content is factually referenced from the ESI handbook (level-1
  lifesaving examples, decision-B example presentations, Table 6-1/6-2 vitals)
- `"Local acuity-escalation heuristic (MFU); …"` — local heuristics (resource
  band, severe-pain escalation) that are not standard content
- `"MFU Triage — …"` / `"MFU OPD manual v1"` — local MFU manual content; shown in
  the admin viewer as *MFU manual (v1)* rather than blank

The criteria document's top-level `source_standards` block lists each standard
(name, edition, URL) — MOPH ED Triage first, the MFU manual second, and the ESI
handbook last as a structure/content reference only — and is displayed with a
link in the admin Screening Criteria tab.

## v1-inherited rule citations (July 2026)

The rules carried over from criteria v1 (level-1 criteria, danger vitals, the six
original triage tuples, both fast tracks, and the red-flag/scale/measurement
questions of the 14 original complaint templates) carry standard citations in
v2, mapped **per rule by what the rule actually checks**. Honesty rules used for
the mapping:

- **Concept-level, verified only.** Where the ESI handbook is co-cited, the PDF
  was fetched and its chapter structure verified before citing: ch. 3 =
  decision point A (lifesaving intervention), ch. 4 = decision point B
  (high-risk presentation), ch. 6 = decision point D (high-risk vital signs;
  Table 6-1 age-banded pediatric vitals, Table 6-2 temperature red flags). No
  page numbers are cited — only chapters, decision points, and tables actually
  seen in the handbook.
- **MFU co-citation retained.** The original `MFU Triage — …` section citation
  stays as a co-citation (it is the true immediate source). Questions that
  previously had no citation carry
  `MFU OPD manual (คู่มือเกณฑ์การคัดกรองผู้ป่วย)` as the co-citation.
- **No shaky ESI claims.** Rules with no clean ESI analogue cite
  `MOPH ED Triage (5-level)` + MFU only: BP thresholds (hypertensive crisis —
  blood pressure is *not* in the ESI decision-D vitals table), obstetric
  labor/GA-window rules, TB isolation, and the ENT 24-hour acceptance window.
  Local heuristics (resource band, severe uncontrolled pain) are labelled as
  such, never attributed to ESI.
- **Infrastructure is not standards material.** `department_rules` and the
  `routing_table` keep their MFU-only citations — they describe MFU's OPD
  structure, not published triage criteria.
- The BEFAST stroke fast track and stroke-screen questions additionally cite
  `BE-FAST stroke recognition`.
