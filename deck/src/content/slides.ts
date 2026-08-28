/**
 * Every word on every slide, in one file. Layouts carry no strings.
 *
 * Source: PITCH_DECK.md. Where this file departs from that document it is
 * because the document has gone stale against the build — each departure is
 * commented with the date and the doc that supersedes it. Do not "restore"
 * them to match PITCH_DECK.md without checking the running app first.
 *
 * `[[key]]` tokens resolve against content/fills.ts at render time.
 */
import {
  BUSINESS_CASE,
  BUSINESS_CAVEAT,
  BUSINESS_NOTE,
  BUSINESS_TIERS,
} from './business';
import { IMPACT_CARD, IMPACT_ITEMS } from './impact';
import { PILOT_OUTCOME, PILOT_TABLE } from './pilot';
import { PROBLEM_ITEMS } from './problems';
import { SOLUTION_BRAND, SOLUTION_ITEMS } from './solution';
import { PREP_COLUMNS, PREP_FOOTER } from './prep';
import type { Slide } from './types';

export const SLIDES: Slide[] = [
  /* ── Cover — the room-settling slide, off the timing rail ─────────────── */
  {
    id: 'cover',
    section: 'cover',
    budgetSec: 0,
    presenter: 'TH',
    layout: 'cover',
    /* MALI = Multilingual Assistant with Local Intelligence. "with", not "by":
       "by" reads as a vendor called Local Intelligence, which does not exist —
       the team is notuning. "with" states the property the product actually
       claims, that the intelligence runs inside the hospital. The accent letter
       is the teal L, the same cut the design system's Wordmark uses. */
    wordmark: { name: 'MA', accent: 'L', product: 'I Prescreening' },
    tagline: 'Multilingual Assistant with Local Intelligence',
    team: { label: 'developed by team', name: 'notuning' },
    headline: {
      th: 'บูธคัดกรองผู้ป่วยนอกด้วย AI',
      en: 'AI OPD Pre-Screening Booth',
    },
    notes: [
      'พูดโครงสร้างการนำเสนอใน 15 วินาทีแรก: "เราจะสลับภาษาไทยและอังกฤษ — เนื้อหาเดียวกัน ไม่พูดซ้ำ"',
      'อย่าเพิ่งพูดคำว่า AI ในสไลด์ถัดไป — เปิดด้วยปัญหา ไม่ใช่เทคโนโลยี',
    ],
    source: 'PITCH_DECK.md §0',
  },

  /* ── §1 Problem & ROI — 1:30, TH lead ────────────────────────────────── */
  {
    id: 'hook',
    section: 'problem',
    number: 1,
    budgetSec: 30,
    presenter: 'TH',
    layout: 'hero',
    headline: {
      /* Rewritten by a native speaker. Hers states the premise — the screening
         point is the first thing a patient meets — and then the consequence,
         which is exactly what the numbers below quantify. The break between
         the two is hers. */
      th: 'จุดคัดกรอง คือด่านแรก\nที่ผู้ป่วยต้องเผชิญ',
      /* Her hierarchy: the premise carries the size, the consequence sits
         under it smaller. No teal accent any more — the two sizes already do
         that work, and colouring a phrase as well would be saying it twice. */
      subTh: 'เมื่อจำนวนผู้ป่วยที่เข้ามารับบริการเพิ่มขึ้น\nความต้องการในการช่วยเหลือก็เพิ่มขึ้น',
      en: 'The screening point is the first thing every patient meets. As more patients come for care, the need for help grows with them.',
    },
    /* Reframed at her request: these used to be about patients not knowing
       where to go, which made the slide an argument about confusion. She asked
       for the number of people using the service instead — so the split is now
       appointment versus no appointment, which is also exactly what the export
       measures. The confusion is a consequence; the volume is the fact. */
    stats: {
      total: { fact: 'encounters7d', label: 'ครั้งที่เข้ารับบริการ ใน 7 วัน' },
      split: [
        { fact: 'appointments7d', label: 'มีนัดหมายล่วงหน้า' },
        { fact: 'walkIns7d', label: 'เข้ามารับบริการโดยไม่ได้นัดหมาย' },
      ],
      hero: {
        fact: 'walkInsPerDay',
        label: 'คนต่อวัน ที่ต้องเริ่มต้นที่จุดคัดกรอง',
        sub: '≈440 patients a day arrive without an appointment',
      },
      source: 'ที่มา: รายงาน prescreening_7Day · ศูนย์การแพทย์ มฟล.',
    },
    notes: [],
    source: 'docs/his-integration.md',
  },
  {
    id: 'problems',
    section: 'problem',
    number: 2,
    budgetSec: 30,
    presenter: 'TH',
    layout: 'problems',
    eyebrow: { th: 'ปัญหาที่พบ', en: 'THE PROBLEMS' },
    headline: {
      /* Corrected by a native speaker: her topic line verbatim. It no longer
         counts the problems or claims they happen every day — so the English
         subtitle stopped saying "four ... every single day" as well. */
      th: 'ปัญหาที่พบเจอได้ ณ จุดคัดกรอง',
      accent: 'ณ จุดคัดกรอง',
      /* Muted, not teal: the tail names the place, it does not carry the turn
         in the sentence the way slide 2's does. */
      accentTone: 'muted',
      en: 'What we run into at the screening point',
    },
    items: PROBLEM_ITEMS,
    notes: [],
  },
  {
    id: 'solution',
    section: 'problem',
    number: 3,
    budgetSec: 30,
    presenter: 'TH',
    layout: 'solution',
    brand: SOLUTION_BRAND,
    eyebrow: { th: 'ทางออกของเรา', en: 'OUR SOLUTION' },
    headline: {
      /* Her topic line verbatim. The old headline ("เราจึงพา MALI เข้ามา…")
         was struck out whole — it framed MALI as something we bring in, where
         hers names what she is. */
      th: 'MALI — ผู้ช่วยอัจฉริยะประจำจุดคัดกรอง',
      accent: 'MALI',
      en: 'MALI — an intelligent assistant at the screening point',
    },
    items: SOLUTION_ITEMS,
    notes: [],
  },
  {
    id: 'impact',
    section: 'problem',
    number: 4,
    budgetSec: 30,
    presenter: 'TH',
    layout: 'impact',
    eyebrow: { th: 'ผลลัพธ์ที่คาดหวัง', en: 'EXPECTED IMPACT' },
    headline: {
      /* Hers. "ช่วยแบ่งเบาภาระงาน" — sharing the load rather than
         cutting repetition, which is the friendlier claim and the truer one. */
      th: 'ช่วยแบ่งเบาภาระงาน เพิ่มเวลาให้การดูแลผู้ป่วย',
      en: 'Sharing the workload, giving time back to patient care.',
    },
    card: IMPACT_CARD,
    items: IMPACT_ITEMS,
    flow: [
      { label: 'PATIENT ARRIVES' },
      { label: 'MALI HANDLES FIRST-STAGE SCREENING', strong: true },
      { label: 'NURSE RECEIVES PREPARED INFO' },
      { label: 'MORE TIME FOR PATIENT CARE' },
    ],
    footer: {
      claim: 'MALI turns repetitive prescreening into automated patient intake.',
      caveat:
        'Expected impact based on deployment assumptions. Actual results will vary with patient volume, workflow, and hospital implementation.',
    },
    notes: [],
  },

  /* ── The live demo — a hold screen, not a slide ───────────────────────── */
  {
    id: 'demo',
    section: 'demo',
    /* The largest single block in the pitch. The rail should show that. */
    budgetSec: 240,
    presenter: 'TH',
    coPresenter: 'EN narrates the second scenario',
    layout: 'hold',
    /* Typeset like the cover's MALI lockup, at the room's request. The accent
       lands on the third letter, which is exactly where MA·L·I's teal L sits —
       DE·M·O reads as the same mark, not as a coloured letter. */
    label: { lead: 'DE', accent: 'M', tail: 'O' },
    sub: 'Live on the booth',
    headline: {
      lead: 'en',
      en: 'Demo',
      th: 'สาธิต',
    },
    notes: [
      'Two scenarios only. Do not tour the criteria editor, the metrics dashboard or surveillance.',
      'Close on: the model reads language, the decision is made by deterministic versioned rules encoded from your own manual.',
    ],
    source: 'docs/demo-runbook.md',
  },

  {
    id: 'business',
    section: 'business',
    number: 5,
    budgetSec: 60,
    presenter: 'EN',
    coPresenter: 'TH: one Thai sentence on what the pilot measures',
    layout: 'business',
    eyebrow: { en: 'BUSINESS MODEL' },
    headline: {
      /* English leads: PITCH_DECK §0 puts the commercial half in English
         because that is the language procurement reads contracts in. The Thai
         is kept for the overview grid and the notes panel, not for the slide. */
      lead: 'en',
      en: 'Three ways to deploy MALI',
      accent: 'MALI',
      th: 'สามรูปแบบการติดตั้ง MALI',
    },
    subtitle: 'Software and service carry the value — hardware is the delivery mechanism.',
    note: BUSINESS_NOTE,
    tiers: BUSINESS_TIERS,
    businessCase: BUSINESS_CASE,
    caveat: BUSINESS_CAVEAT,
    notes: [],
  },
  {
    id: 'pilot',
    section: 'business',
    number: 6,
    budgetSec: 40,
    presenter: 'EN',
    layout: 'pilot',
    eyebrow: { en: 'PILOT SUCCESS CRITERIA' },
    headline: {
      lead: 'en',
      en: 'The pilot should prove value, not just that it works.',
      accent: 'prove value',
      th: 'การนำร่องต้องพิสูจน์คุณค่าที่วัดได้',
    },
    lead: 'Establish a baseline before MALI arrives, then measure the same nine metrics throughout. Both halves, every metric — so nothing is chosen after the results are in.',
    table: PILOT_TABLE,
    outcome: PILOT_OUTCOME,
    notes: [
      'The pilot is not a demonstration. Say that out loud — a demo shows it works, this measures whether it was worth doing.',
    ],
  },
  {
    id: 'prep',
    section: 'deployment',
    /* One slide now carries what PITCH_DECK §4 split across three, so it takes
       the section's whole two minutes. */
    number: 6,
    budgetSec: 120,
    presenter: 'EN',
    coPresenter: 'TH answers the hospital-side items',
    layout: 'checklist',
    eyebrow: { en: 'DEPLOYMENT PREP CHECKLIST' },
    headline: {
      lead: 'en',
      en: 'Everything runs on your hardware. Three API calls are all that crosses the boundary.',
      accent: 'your hardware',
      th: 'ทุกอย่างทำงานบนเครื่องของโรงพยาบาล',
    },
    columns: PREP_COLUMNS,
    footer: PREP_FOOTER,
    notes: [
      'Say the sign-in item is not built yet, in those words.',
      'The HIS test endpoint is the long pole. Ask for it in the room.',
      'The VRAM table is the proof that on-prem is engineered, not aspirational — let them photograph it.',
    ],
    source: 'PITCH_DECK.md §4 · docs/hospital-integration-security.md · docs/his-integration.md',
  },
  /* ── Q&A — a hold screen, off the timing rail ─────────────────────────── */
  {
    id: 'questions',
    section: 'ask',
    number: 10,
    /* Q&A is not on the clock, so it leaves the rail — which then measures
       exactly the part of the pitch that is timed. */
    budgetSec: 0,
    presenter: 'EN',
    layout: 'hold',
    label: 'Questions?',
    sub: 'ถามได้ทั้งสองภาษา',
    headline: {
      lead: 'en',
      en: 'Questions',
      th: 'คำถาม',
    },
    mark: {
      size: 420,
      /* The design system's own mixer, not a hand-written cycle. It already
         does everything this slide needs and the deck's fixed-interval cycle
         could not: it picks its next act at random, never plays the same one
         twice running, and — because each act returns its own length — waits
         for the act to finish before starting the next. Its three acts are
         drawn from `acts`, so `nongExplode` cannot appear. The old cycle
         switched every 8s regardless, which cut acts off mid-flight. */
      motion: 'nongShowreel',
      /* All four, bounce included. The showreel's default set is the three the
         booth's attract screen was tuned against; asking for the fourth here
         leaves that default — and so the kiosk — untouched. */
      acts: ['wave', 'heartbeat', 'sway', 'bounce'],
    },
    /* Same credit as the cover, in the corner rather than under the wordmark.
       This slide is on screen for the entire Q&A — longer than any other — so
       the one thing worth repeating is who built it. */
    team: { label: 'developed by team', name: 'notuning' },
    notes: [
      'The ask is no longer on a slide — make it out loud before opening the floor: a pilot at OPD, a HIS test endpoint, the triage manual, a named clinical owner.',
      'Answer in the language the question is asked in. Decide in advance who takes clinical and who takes technical.',
    ],
    source: 'PITCH_DECK.md §6',
  },
];

export const SLIDE_IDS = SLIDES.map((s) => s.id);
