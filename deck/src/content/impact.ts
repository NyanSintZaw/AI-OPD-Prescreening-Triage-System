/**
 * Slide 5's copy, corrected by a native speaker.
 *
 * Her most valuable change is not a translation. She turned both figures from
 * point estimates into ranges — 50% became 45–50%, ≈220 became ≈200–220 — and
 * put "not a measured result" on each in English. A single number reads as
 * something someone counted; a range reads as something someone modelled,
 * which is what these are. Do not tighten them back to a single figure to make
 * the slide look more confident.
 *
 * The ≈200–220 is derived: 440 daily walk-ins times the 45–50% target. The 440
 * is the one real number here and must keep agreeing with FACTS.walkInsPerDay.
 */
import type { Slide } from './types';

type Impact = Extract<Slide, { layout: 'impact' }>;

export const IMPACT_CARD: Impact['card'] = {
  label: 'TARGET OPERATIONAL IMPACT',
  prefix: 'up to',
  figure: '45–50%',
  th: 'เป้าหมายลดภาระงานคัดกรองเบื้องต้น',
  en: 'Design target; not a measured result.',
  secondary: {
    figure: '≈200–220',
    th: 'คน/วัน จำนวนเคสที่ตั้งเป้าให้ MALI ช่วยลดภาระงานคัดกรองเบื้องต้น',
    /* Word joiners around the dash: without them the line breaks as "45–" /
       "50%", which reads as two numbers rather than one range. */
    en: 'Based on 440 daily walk-ins and a 45⁠–⁠50% design target; not a measured result.',
  },
};

export const IMPACT_ITEMS: Impact['items'] = [
  {
    label: 'SAVE TIME',
    th: 'ลดภาระงานคัดกรองเบื้องต้นของพยาบาล',
    en: 'Takes first-stage screening off the nurse',
  },
  {
    label: 'RETURN TIME TO NURSES',
    th: 'คืนเวลาให้พยาบาลในการดูแลผู้ป่วยได้มากขึ้น',
    en: 'Gives nurses more time back for patient care',
  },
  {
    label: 'IMPROVE ACCESS',
    th: 'ลดข้อจำกัดด้านภาษาและการเข้าถึงบริการ',
    en: 'Lowers language and access barriers to care',
  },
];
