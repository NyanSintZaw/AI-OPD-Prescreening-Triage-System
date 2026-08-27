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
import { PILOT_OUTCOME, PILOT_TABLE } from './pilot';
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
      /* The break is deliberate: the first sentence is the wait, the second is
         the thing nobody knows yet. They should not run together. */
      th: 'ทุกคนที่เดินเข้ามาในโรงพยาบาล ต้องยืนรอด้วยสายตาที่ไม่แน่ใจ และเดินไปถามใครคนหนึ่ง\nก่อนจะมีใครรู้ว่าเขาควรไปที่ไหน',
      accent: 'เขาควรไปที่ไหน',
      en: 'Everybody who walks into the hospital has to wait with uncertain eyes, and find and ask a human, before anyone knows where they belong.',
    },
    stats: {
      total: { fact: 'encounters7d', label: 'ครั้งที่เข้ารับบริการ ใน 7 วัน' },
      split: [
        { fact: 'appointments7d', label: 'มีนัดหมายอยู่แล้ว' },
        { fact: 'walkIns7d', label: 'ไม่รู้ว่าต้องไปไหน' },
      ],
      hero: {
        fact: 'walkInsPerDay',
        label: 'คนต่อวัน ที่ต้องเดินหาคนถาม',
        sub: '≈440 patients a day arrive with nowhere to go',
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
      th: 'ปัญหาที่เกิดขึ้นทุกวัน ณ จุดคัดกรอง',
      accent: 'ที่จุดคัดกรอง',
      /* Muted, not teal: here the tail names the place, it does not carry the
         turn in the sentence the way slide 2's does. */
      accentTone: 'muted',
      en: 'Four problems that repeat every single day at prescreening',
    },
    /* Order matters — the list fills column-major, so 1 and 2 land in the left
       column and 3 and 4 in the right. */
    items: [
      {
        th: 'ผู้ป่วยต่างชาติสื่อสารภาษาไทยไม่ได้',
        en: 'Foreign patients lack the Thai language skills to be screened',
      },
      {
        th: 'พยาบาลเสียเวลาถามคำถามซ้ำ ๆ จนกำลังคนไม่พอให้บริการ',
        en: 'Nurses consume valuable working time on the same repetitive questions, leaving insufficient personnel to provide service',
      },
      {
        th: 'ผู้ป่วยหนาแน่น รอคัดกรองเป็นแถวยาว',
        en: 'Density of patients waiting to be screened',
      },
      {
        th: 'ผู้ป่วยไม่รู้ว่าแต่ละแผนกอยู่ที่ไหน',
        en: 'Patients are clueless about the location of different departments',
      },
    ],
    notes: [],
  },
  {
    id: 'solution',
    section: 'problem',
    number: 3,
    budgetSec: 30,
    presenter: 'TH',
    layout: 'solution',
    brand: {
      name: 'MA',
      accent: 'L',
      th: 'ผู้ช่วยคัดกรองหลากภาษา\nด้วยปัญญาในพื้นที่',
      en: 'Multilingual Assistant\nwith Local Intelligence',
    },
    eyebrow: { th: 'ทางออกของเรา', en: 'OUR SOLUTION' },
    headline: {
      th: 'เราจึงพา MALI เข้ามาช่วยงานคัดกรอง',
      accent: 'MALI',
      en: 'We bring in MALI to help with prescreening',
    },
    items: [
      {
        th: 'ทำงานได้เหมือนพยาบาลจูเนียร์ รับคำสั่งจากไฟล์ PDF เกณฑ์ของโรงพยาบาล และอ้างอิงแนวทางสุขภาพที่กระทรวงสาธารณสุขประกาศใช้',
        en: 'Works like a junior nurse — listens to your instructions through a hospital criteria PDF while referencing official health guidelines published by MOPH Thailand',
      },
      {
        th: 'ไม่ลาหยุด ไม่พักกลางวัน เพื่อนร่วมงานที่เป็นมนุษย์จึงมีเวลาไปดูแลคนไข้ในแบบที่มีแต่มนุษย์ทำได้',
        en: "She doesn't take a leave or lunch break, so her human coworkers can focus on more humanly care-giving work",
      },
      {
        th: 'ฟังผู้ป่วยต่างชาติได้ เปิดทางให้โรงพยาบาลมีรายได้เพิ่มขึ้น',
        en: 'She can also listen to foreigners, bringing in more revenues',
      },
      {
        th: 'รายงานทุกอย่างที่เธอทำ ให้เพื่อนร่วมงานและพยาบาลอาวุโสรู้ โดยไม่ลังเล',
        en: 'She lets her coworkers and senior nurses know about everything she does, without hesitation',
      },
    ],
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
      th: 'ลดงานซ้ำ เพิ่มเวลาให้การดูแลผู้ป่วย',
      en: 'Less repetitive work. More time for patient care.',
    },
    card: {
      label: 'TARGET OPERATIONAL IMPACT',
      prefix: 'up to',
      figure: '50%',
      th: 'ลดภาระงานคัดกรองเบื้องต้นที่ทำซ้ำ',
      /* The caveat is part of the sentence, not a footnote. A target read as a
         measurement is the one way this slide can mislead a hospital. */
      en: 'Reduction in repetitive manual prescreening workload — a design target, not a measured result',
      secondary: {
        figure: '≈220',
        /* The 440 here is real and must keep agreeing with
           FACTS.walkInsPerDay. It stays as copy because interpolating a
           component mid-Thai-sentence reads worse than this does. */
        th: 'จาก 440 คนต่อวัน ที่ MALI รับไว้ก่อนถึงมือพยาบาล',
        en: 'of the 440 daily walk-ins, handled before a nurse is involved',
      },
    },
    items: [
      {
        label: 'SAVE TIME',
        th: 'ลดเวลาที่ใช้กับคำถามคัดกรองซ้ำ ๆ',
        en: 'Reduce repetitive questions and manual first-stage screening.',
      },
      {
        label: 'RETURN TIME TO NURSES',
        th: 'คืนเวลาให้พยาบาลสำหรับการดูแลผู้ป่วยที่สำคัญกว่า',
        en: 'Nurses focus on clinical judgment, complex cases, and direct patient care.',
      },
      {
        label: 'IMPROVE ACCESS',
        th: 'ช่วยลดอุปสรรคด้านภาษาและเพิ่มการเข้าถึงบริการ',
        en: 'Foreign patients can communicate and begin screening more easily.',
      },
    ],
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
    label: 'DEMO',
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
      cycle: ['nongWaveHello', 'nongHeartbeat', 'nongExplode', 'nongBounce'],
    },
    notes: [
      'The ask is no longer on a slide — make it out loud before opening the floor: a pilot at OPD, a HIS test endpoint, the triage manual, a named clinical owner.',
      'Answer in the language the question is asked in. Decide in advance who takes clinical and who takes technical.',
    ],
    source: 'PITCH_DECK.md §6',
  },
];

export const SLIDE_IDS = SLIDES.map((s) => s.id);
