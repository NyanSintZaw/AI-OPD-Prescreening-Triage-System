import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { CalendarBlank, CaretLeft, CaretRight } from '@phosphor-icons/react';
import { useExitDelay } from '../../hooks/useExitDelay';
import { useFlipPlacement } from './useFlipPlacement';
import {
  addDays,
  addMonths,
  daysBetween,
  fromDateValue,
  localeFor,
  monthGrid,
  sameDay,
  startOfDay,
  startOfMonth,
  toDateValue,
} from './dateRange';

/**
 * The dashboard's calendar range picker.
 *
 * It sits *beside* the rolling chips rather than replacing them, because the
 * two answer different questions. "Last 7 days" is the question a nurse asks
 * every shift and should cost one click; "the week of the outbreak" is the
 * question she asks twice a year and no set of chips can hold. Chips are the
 * fast path, this is the precise one, and picking a range clears the chip so
 * the board never shows two answers at once.
 *
 * Two months side by side, a hover preview of the range while the second end
 * is being chosen, and no future days — the range-picker checklist that MILA's
 * own `DateField` documented and then skipped, because every date in that
 * product is a single forward-looking moment and there was nowhere to select a
 * range. The parts that did carry across are its: month reachable directly
 * rather than by clicking "next" four times, one roving tabstop for the whole
 * grid, and local-time date maths throughout.
 */

const EXIT_MS = 140;

/** The API caps a window at 90 days; the picker says so rather than letting a
 *  nurse select 200 and get a 400 back. */
const MAX_SPAN = 90;

export interface DateRange {
  /** `YYYY-MM-DD` */
  from: string;
  to: string;
}

export function DateRangeField({
  value,
  onChange,
  label,
}: {
  /** Null while a rolling chip owns the period. */
  value: DateRange | null;
  onChange: (range: DateRange) => void;
  label: string;
}) {
  const { t, i18n } = useTranslation();
  const id = useId();
  const wrapRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const [open, setOpen] = useState(false);
  const mounted = useExitDelay(open, EXIT_MS);
  const { dropUp } = useFlipPlacement(wrapRef, panelRef, open, { fallbackHeight: 360 });

  const today = useMemo(() => startOfDay(new Date()), []);
  const selected = useMemo(
    () => ({ from: fromDateValue(value?.from), to: fromDateValue(value?.to) }),
    [value],
  );

  /** The month shown on the left; the right is always the one after it. */
  /** Normalised to the 1st: the key handler compares day cursors against it,
   *  and a `month` still carrying the 26th would shift the view when the
   *  cursor moved to the 10th of the same month. */
  const [month, setMonth] = useState(() => startOfMonth(addMonths(selected.from ?? today, -1)));
  /** The first click of a new range, before the second lands. */
  const [anchor, setAnchor] = useState<Date | null>(null);
  /** What the pointer is over, so the range can be previewed as it is drawn. */
  const [hover, setHover] = useState<Date | null>(null);
  const [cursor, setCursor] = useState<Date>(selected.from ?? today);

  useEffect(() => {
    if (!open) return;
    setAnchor(null);
    setHover(null);
    setCursor(selected.from ?? today);
    setMonth(startOfMonth(addMonths(selected.from ?? today, -1)));
  }, [open, selected.from, today]);

  // Outside press closes. `pointerdown`, not `click`: a click that starts
  // inside and ends outside should not count as leaving.
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e: PointerEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    /* Escape belongs on the document, not on the grid. The grid's own handler
       only fires once a day cell has focus, and opening the panel leaves focus
       on the trigger — so Escape did nothing until you had arrowed into the
       calendar first. Propagation still stops, so a dialog hosting this later
       does not close along with it. */
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      e.stopPropagation();
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener('pointerdown', onDown);
    document.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('pointerdown', onDown);
      document.removeEventListener('keydown', onKey, true);
    };
  }, [open]);

  /** The pair currently being described — committed, or anchor + pointer. */
  const preview = useMemo(() => {
    if (anchor) {
      const other = hover ?? cursor;
      return other < anchor ? { start: other, end: anchor } : { start: anchor, end: other };
    }
    if (selected.from && selected.to) return { start: selected.from, end: selected.to };
    return null;
  }, [anchor, hover, cursor, selected]);

  const span = preview ? daysBetween(preview.start, preview.end) : 0;
  const tooLong = span > MAX_SPAN;

  function pick(day: Date) {
    if (day > today) return;
    if (!anchor) {
      setAnchor(day);
      setCursor(day);
      return;
    }
    const [start, end] = day < anchor ? [day, anchor] : [anchor, day];
    if (daysBetween(start, end) > MAX_SPAN) return;
    onChange({ from: toDateValue(start), to: toDateValue(end) });
    setAnchor(null);
    setOpen(false);
  }

  function onGridKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const moves: Record<string, number> = {
      ArrowRight: 1,
      ArrowLeft: -1,
      ArrowDown: 7,
      ArrowUp: -7,
    };
    if (event.key in moves) {
      event.preventDefault();
      const next = addDays(cursor, moves[event.key]);
      if (next > today) return;
      setCursor(next);
      setHover(next);
      // Follow the cursor out of the visible pair of months.
      if (next < month) setMonth(startOfMonth(next));
      if (next >= addMonths(month, 2)) setMonth(startOfMonth(addMonths(next, -1)));
      return;
    }
    if (event.key === 'PageUp' || event.key === 'PageDown') {
      event.preventDefault();
      setMonth(startOfMonth(addMonths(month, event.key === 'PageDown' ? 1 : -1)));
      return;
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      pick(cursor);
      return;
    }
  }

  const locale = localeFor(i18n.language);
  const monthName = (d: Date) =>
    d.toLocaleDateString(locale, { month: 'long', year: 'numeric' });
  const dayLabel = (d: Date) =>
    d.toLocaleDateString(locale, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });

  /** Monday-first initials, from the locale rather than a hardcoded list. */
  const weekdays = useMemo(() => {
    const monday = new Date(2024, 0, 1); // a known Monday
    return Array.from({ length: 7 }, (_, i) =>
      addDays(monday, i).toLocaleDateString(locale, { weekday: 'narrow' }),
    );
  }, [locale]);

  const triggerText =
    selected.from && selected.to
      ? `${selected.from.toLocaleDateString(locale, { day: 'numeric', month: 'short' })} – ${selected.to.toLocaleDateString(locale, { day: 'numeric', month: 'short', year: 'numeric' })}`
      : t('dashPickDates');

  function renderMonth(base: Date) {
    return (
      <div className="cal-month" key={base.toISOString()}>
        <p className="cal-month-name">{monthName(base)}</p>
        <div className="cal-weekdays" aria-hidden="true">
          {weekdays.map((d, i) => (
            <span key={i}>{d}</span>
          ))}
        </div>
        <div className="cal-days">
          {monthGrid(base).map((day) => {
            /* Days belonging to a neighbouring month are held as empty cells,
               not drawn. With two months side by side the trailing days of the
               left one are the leading days of the right one, so every date in
               the gap appeared twice — and the second copy sat immediately
               under a real, clickable version of itself. The cell still exists
               so the weeks stay aligned and the panel keeps its height. */
            if (day.getMonth() !== base.getMonth()) {
              return <span key={day.toISOString()} className="cal-day-blank" aria-hidden="true" />;
            }
            const future = day > today;
            const isStart = preview ? sameDay(day, preview.start) : false;
            const isEnd = preview ? sameDay(day, preview.end) : false;
            const inRange = preview ? day > preview.start && day < preview.end : false;
            return (
              <button
                key={day.toISOString()}
                type="button"
                role="gridcell"
                id={`${id}-d-${toDateValue(day)}`}
                // Roving tabindex: one stop for the grid, not eighty-four.
                tabIndex={sameDay(day, cursor) ? 0 : -1}
                disabled={future}
                aria-label={dayLabel(day)}
                aria-selected={isStart || isEnd}
                aria-current={sameDay(day, today) ? 'date' : undefined}
                className="cal-day"
                data-today={sameDay(day, today) || undefined}
                data-start={isStart || undefined}
                data-end={isEnd || undefined}
                data-in-range={inRange || undefined}
                onPointerEnter={() => setHover(day)}
                onFocus={() => setCursor(day)}
                onClick={() => pick(day)}
              >
                {day.getDate()}
              </button>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className="cal-wrap" ref={wrapRef}>
      <button
        ref={triggerRef}
        type="button"
        className={`cal-trigger ${value ? 'is-set' : ''}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={label}
        onClick={() => setOpen((v) => !v)}
      >
        <CalendarBlank size={16} weight="bold" aria-hidden="true" />
        {triggerText}
      </button>

      {mounted ? (
        <div
          ref={panelRef}
          className="cal-panel"
          role="dialog"
          aria-label={label}
          data-leaving={!open || undefined}
          data-drop-up={dropUp || undefined}
          onMouseLeave={() => setHover(null)}
        >
          <div className="cal-head">
            <button
              type="button"
              className="icon-btn cal-nav"
              onClick={() => setMonth(startOfMonth(addMonths(month, -1)))}
              aria-label={t('dashPrevMonth')}
            >
              <CaretLeft size={16} weight="bold" aria-hidden="true" />
            </button>
            <button
              type="button"
              className="icon-btn cal-nav"
              // Never past this month: there is nothing to select in the future.
              disabled={addMonths(month, 1) >= startOfMonth(today)}
              onClick={() => setMonth(startOfMonth(addMonths(month, 1)))}
              aria-label={t('dashNextMonth')}
            >
              <CaretRight size={16} weight="bold" aria-hidden="true" />
            </button>
          </div>

          {/* One key handler for both months: only the cursor cell is ever
              focused, so the event lands here whichever month it is in. */}
          <div className="cal-months" role="grid" ref={gridRef} onKeyDown={onGridKeyDown}>
            {renderMonth(month)}
            {renderMonth(addMonths(month, 1))}
          </div>

          <p className="cal-foot" aria-live="polite">
            {anchor
              ? t('dashPickEnd')
              : tooLong
                ? t('dashRangeTooLong', { n: MAX_SPAN })
                : span > 0
                  ? t('dashRangeSpan', { n: span })
                  : t('dashPickStart')}
          </p>
        </div>
      ) : null}
    </div>
  );
}
