/**
 * Every number PITCH_DECK.md marks `[FILL]`, in one file, so filling them in
 * the night before touches no layout. `value: null` renders the obvious chip.
 *
 * PITCH_DECK §5, and it is a hard rule: never ship the deck with a visible
 * [FILL]. Either the number, or set `value` to the sentence "to be measured in
 * the pilot" — both are fine; a bracket on the projector is not. Press `A`
 * during a rehearsal to see what is still empty.
 *
 * This file holds numbers that are MISSING. Numbers that are REAL live in
 * facts.ts, which requires a source for each. Keeping them apart matters:
 * they have opposite failure modes, and merging them would let a real number
 * quietly acquire a [FILL] chip's forgiveness.
 */
import type { SlideId } from './types';

export interface Fill {
  /** For the #/audit register. */
  label: string;
  /** null = not yet measured. */
  value: string | number | null;
  unit?: string;
  /** Mirrors PITCH_DECK §5's register table. */
  slides: SlideId[];
  /** How to get it. */
  source: string;
  /** §5 says assign an owner AND a date to each. */
  owner?: string;
  /** Printed small beside the number when it lands. */
  caveat?: string;
}

/* Empty, and that is the finished state: no slide currently shows a [FILL].
   The machinery stays because numbers come back — the moment a price or a pilot
   figure needs a placeholder, it is one entry here and a [[token]] in the copy,
   with the audit screen catching it before a projector does. */
export const FILLS: Record<string, Fill> = {
};

export type FillKey = keyof typeof FILLS;

/** How many are still empty. The rehearsal target is zero. */
export function unfilledCount(): number {
  return Object.values(FILLS).filter((f) => f.value == null).length;
}
