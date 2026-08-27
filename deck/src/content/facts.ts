/**
 * Numbers that are REAL. `source` is mandatory — PITCH_DECK §0 rule 2: every
 * number on a slide must be traceable, and none may be invented.
 *
 * `caveat` exists because docs/ai-quality-evaluation.md insists the evaluation
 * numbers never travel without one: the corpora are small, the intervals are
 * wide, and the evals measure the pipeline rather than the criteria's clinical
 * validity. <FactNumber> will not render a value without its source, so that
 * rule is structural rather than a habit someone has to remember.
 */

export interface Fact {
  value: number;
  /** Where a raw number would mislead — "0/18 (CI95 0–18.5%)" rather than "0". */
  display?: string;
  label: { th: string; en: string };
  source: string;
  caveat?: string;
}

export const FACTS = {
  /* ── The MFU 7-day export — the deck's hard data ────────────────────── */
  encounters7d: {
    value: 11_624,
    label: { th: 'ครั้งการมารับบริการ ใน 7 วัน', en: 'encounters in 7 days' },
    source: 'MFU Prescreen_7Day export',
  },
  appointments7d: {
    value: 8_552,
    label: { th: 'นัดหมายล่วงหน้า', en: 'appointment follow-ups' },
    source: 'MFU Prescreen_7Day export',
  },
  walkIns7d: {
    value: 3_072,
    label: { th: 'ผู้ป่วย walk-in', en: 'walk-ins' },
    source: 'MFU Prescreen_7Day export',
  },
  walkInsPerDay: {
    value: 440,
    display: '≈ 440',
    label: { th: 'walk-in ต่อวัน', en: 'walk-ins per day' },
    source: 'MFU Prescreen_7Day export, 3,072 over 7 days',
  },
  routableDepts: {
    value: 11,
    label: { th: 'แผนกที่ระบบส่งต่อได้', en: 'routable departments' },
    source: 'docs/his-integration.md — 7,393 of 11,606 routed encounters, ≈64%',
  },

  /* ── Measured quality — appendix only, never the main flow ──────────── */
  extractionEval: {
    value: 81,
    display: '81/81',
    label: { th: 'การสกัดอาการถูกต้อง', en: 'extraction cases correct' },
    source: 'evals/reports/extraction-20260822T095610Z.json',
    caveat: 'a corpus of 81 — measures the pipeline, not clinical validity',
  },
  undertriage: {
    value: 0,
    display: '0/18',
    label: { th: 'ประเมินต่ำกว่าความจริง', en: 'undertriage on critical vignettes' },
    source: 'scripts/run_triage_eval.py over evals/vignettes.json',
    caveat:
      'CI95 0–18.5%. Read the interval, not the point estimate: n=18 is too small to claim a low rate, only to say none of these eighteen was missed',
  },
  qwk: {
    value: 0.946,
    label: { th: 'ค่าความสอดคล้อง QWK', en: 'quadratic weighted kappa' },
    source: 'Triage eval, 2026-08-11 run',
    caveat: 'agreement with the criteria’s own reference labels, not with patient outcomes',
  },
  validatorLeaks: {
    value: 0,
    label: { th: 'ข้อมูลรั่วถึงผู้ป่วย', en: 'validator leaks to patients' },
    source: 'Triage eval — level, colour, diagnosis and prescription, both languages',
  },
  unitTests: {
    value: 385,
    display: '385+',
    label: { th: 'unit test', en: 'unit tests' },
    source: 'hospital-hotline-assistant-api/tests — no live Google or DB calls',
  },
} as const satisfies Record<string, Fact>;

export type FactKey = keyof typeof FACTS;
