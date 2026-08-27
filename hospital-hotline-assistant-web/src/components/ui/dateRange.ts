/**
 * Wall-clock dates for the dashboard's period picker.
 *
 * All of it deliberately local-time. `toISOString()` converts to UTC first, so
 * in Bangkok (UTC+7) a date of "26 Aug" round-trips as "25 Aug 17:00" and the
 * calendar selects the wrong day. Every value here is built from local parts
 * and parsed back from them.
 */

const pad = (n: number) => String(n).padStart(2, '0');

/** `YYYY-MM-DD` from local parts — the format the API's `from`/`to` take. */
export function toDateValue(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/**
 * Parse `YYYY-MM-DD` into a local `Date`, or null.
 *
 * Built from parts rather than handed to `new Date(string)`, which reads a
 * bare date as UTC midnight — the same off-by-one-day the writer above avoids.
 */
export function fromDateValue(value: string | null | undefined): Date | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value.trim());
  if (!match) return null;
  const [, y, m, d] = match;
  const date = new Date(Number(y), Number(m) - 1, Number(d));
  // Rejects the 31st of February, which the constructor rolls into March.
  if (date.getMonth() !== Number(m) - 1 || date.getDate() !== Number(d)) return null;
  return date;
}

/** Midnight local — the unit the grid compares in. */
export function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

export function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

/**
 * Add months without the 31st-of-January problem: `setMonth(1)` on the 31st
 * gives the 2nd or 3rd of March, so paging forward from the 31st would skip
 * February entirely.
 */
export function addMonths(date: Date, months: number): Date {
  const target = new Date(date.getFullYear(), date.getMonth() + months, 1);
  const lastDay = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
  target.setDate(Math.min(date.getDate(), lastDay));
  return target;
}

export const sameDay = (a: Date, b: Date): boolean =>
  a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

/** Whole days from `a` to `b`, inclusive of both ends. */
export const daysBetween = (a: Date, b: Date): number =>
  Math.round((startOfDay(b).getTime() - startOfDay(a).getTime()) / 86_400_000) + 1;

/** The 1st of the month `date` falls in. */
export function startOfMonth(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

/**
 * Six weeks of cells for one month, Monday-first.
 *
 * Always 42 so the popover does not change height between a month that needs
 * five rows and one that needs six — with two months side by side, one growing
 * would shunt the other. The cells that fall outside the month are rendered
 * blank rather than dropped, for the same reason.
 */
export function monthGrid(month: Date): Date[] {
  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const lead = (first.getDay() + 6) % 7; // getDay() is Sunday-0; shift to Monday-0
  const start = addDays(first, -lead);
  return Array.from({ length: 42 }, (_, i) => addDays(start, i));
}

/**
 * Gregorian regardless of language.
 *
 * `th-TH` defaults to the Buddhist era, so a Thai nurse would read 2569 on this
 * calendar and 2026 on the session log two clicks away. Until the product
 * decides on an era this pins the one the rest of the app already shows.
 */
export const localeFor = (language: string): string =>
  language === 'th' ? 'th-TH-u-ca-gregory' : 'en-GB';
