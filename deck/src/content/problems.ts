/**
 * Slide 3's copy.
 *
 * The Thai here was corrected by a native speaker on a marked-up print, and
 * her wording is authoritative — it is not to be "improved" back toward a
 * literal translation of the English. Two things changed in substance, not
 * just phrasing:
 *
 *   - The headline dropped "สี่" (four) and "ทุกวัน" (every day). It now names
 *     the topic rather than counting or claiming a frequency, so the English
 *     subtitle had to stop saying "four problems every single day" too.
 *   - Item 2 was about nurses losing time to repeated questions. She reframed
 *     it as staffing capacity, and supplied the English herself: "Screening
 *     capacity limited by staff shortages."
 *
 * Order is load-bearing: the list fills column-major, so items 0 and 1 stack in
 * the left column and 2 and 3 in the right. Her corrections were written in
 * place over the lines they replace, so these four keep those exact positions.
 */
import type { Slide } from './types';

type Problems = Extract<Slide, { layout: 'problems' }>;

export const PROBLEM_ITEMS: Problems['items'] = [
  {
    th: 'การสื่อสารด้านภาษาของผู้ป่วยที่เป็นต่างชาติ',
    /* Her Thai names the topic rather than asserting a deficit, so the English
       follows: a barrier between two parties, not something the patient lacks. */
    en: 'Language barriers with foreign patients',
  },
  {
    /* Her typed wording. The handwritten line adds "การคัดกรอง" on the end,
       but that pushes the line to wrap and Chrome breaks it inside คัดกรอง —
       a word split in half reads worse than the shorter phrase, and the
       English below already says the shortage is a screening one.
       Spelling: standard บุคลากร; her typed note had บุคคลากร. Confirm. */
    th: 'จำนวนบุคลากรไม่เพียงพอต่อการให้บริการ',
    en: 'Screening capacity limited by staff shortages',
  },
  {
    th: 'ความหนาแน่นของคนไข้ที่รอคัดกรอง',
    en: 'Crowding among patients waiting to be screened',
  },
  {
    th: 'ผู้ป่วยไม่ทราบถึงตำแหน่งที่ตั้งของแผนกต่าง ๆ',
    /* "Clueless" was doing no work and read as blame. */
    en: 'Patients do not know where each department is',
  },
];
