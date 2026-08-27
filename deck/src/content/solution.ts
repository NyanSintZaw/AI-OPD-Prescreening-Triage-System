/**
 * Slide 4's copy.
 *
 * The Thai was rewritten by a native speaker on a marked-up print, and her
 * wording is authoritative. Two of her changes are substantive and should not
 * be quietly reverted toward the older, punchier English:
 *
 *   - Item 3 no longer claims extra hospital revenue. It says she speaks
 *     several languages and stops there. That claim was unevidenced anyway,
 *     and a revenue promise on a clinical slide invites the wrong argument.
 *   - Item 4 is now about handing the screening record to a nurse for
 *     assessment, rather than about her "reporting everything she does". That
 *     is the deck's core safety position — a nurse decides — stated where a
 *     hospital audience actually looks for it.
 *
 * The English lines were rewritten to match her Thai rather than kept from the
 * previous draft, because several no longer said the same thing.
 */
import type { Slide } from './types';

type Solution = Extract<Slide, { layout: 'solution' }>;

/** The lockup under the mark. Her wording, from the boxed note. */
export const SOLUTION_BRAND: Solution['brand'] = {
  name: 'MA',
  accent: 'L',
  th: 'ผู้ช่วยคัดกรองที่พูดได้หลายภาษา\nและพร้อมเรียนรู้งานตามมาตรฐานของโรงพยาบาล',
  /* Unchanged: this is the MALI acronym itself, not a description, so it is
     not hers to restate — Multilingual Assistant with Local Intelligence. */
  en: 'Multilingual Assistant\nwith Local Intelligence',
};

export const SOLUTION_ITEMS: Solution['items'] = [
  {
    th: 'ผู้ช่วยพยาบาลที่คัดกรองอาการของผู้ป่วยโดยอ้างอิงจากเกณฑ์และแนวทางที่ใช้ภายในโรงพยาบาล',
    en: 'A nursing assistant that screens symptoms against the criteria and guidelines your hospital already uses',
  },
  {
    th: 'เตรียมพร้อมให้บริการในการช่วยคัดกรองอยู่ตลอดเวลา',
    en: 'Ready to help with screening at any hour',
  },
  {
    /* Her text reads หลากลายภาษา, which is not a word — almost certainly
       หลากหลาย with a dropped ห. Confirm with her. */
    th: 'พูดคุยสื่อสารกับผู้ป่วยได้หลากหลายภาษา',
    en: 'Talks with patients in several languages',
  },
  {
    th: 'ส่งต่อข้อมูลการคัดกรองให้พยาบาล เพื่อประกอบการประเมินและดำเนินการต่อ',
    en: 'Passes the screening record to a nurse for assessment and next steps',
  },
];
