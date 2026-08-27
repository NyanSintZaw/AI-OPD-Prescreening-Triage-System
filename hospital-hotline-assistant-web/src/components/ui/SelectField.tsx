import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
} from 'react';
import { CaretDown, Check } from '@phosphor-icons/react';
import { useExitDelay } from '../../hooks/useExitDelay';
import { useFlipPlacement } from './useFlipPlacement';

/**
 * MALI's dropdown.
 *
 * A native `<select>` renders the operating system's list, which is the one
 * surface in the app the brand cannot reach — grey on Windows, translucent on
 * macOS, and on neither does it know what Mali Teal is or what a focus ring
 * looks like here. The nurse portal's filters and the review dialog's
 * department picker were all built out of them, so the controls a nurse touches
 * most often were the only ones that looked like they belonged to something
 * else.
 *
 * This is the WAI-ARIA editable combobox: the trigger *is* the text field.
 * Click it and it becomes editable; type and the list narrows in place. That
 * matters more than it sounds — a separate search box inside the popup is
 * reasonable machinery for the department list and absurd for five triage
 * levels, and this portal has both. Making the trigger the input means the same
 * control behaves the same way at every length, and a five-option list simply
 * narrows to one on the first keystroke.
 *
 * Deliberately not a `<select>` underneath. A hidden native control kept in
 * sync would give form participation for free, but it also re-introduces the
 * thing being replaced: browsers fire the OS picker for a focused select, and
 * the two would fight over the keyboard. Every caller here submits through
 * React state, so nothing is lost.
 */

export interface SelectOption {
  value: string;
  label: string;
  /** Optional second line — a department's floor, a level's response time. */
  hint?: string;
  /** A mark that belongs to the option itself, not a decoration of it — the
   *  triage badge on a level, and nothing on a department, which has no colour
   *  in this system to borrow. Reserved on every row once any row has one, so
   *  the labels still line up. */
  icon?: ReactNode;
}

export interface SelectFieldProps {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  /** Rendered above the control, and wired to it as a real `<label>`. */
  label?: ReactNode;
  placeholder?: string;
  disabled?: boolean;
  id?: string;
  /** Applied to the wrapper, for width and grid placement. */
  className?: string;
  /** Only needed when there is no visible `label`. */
  'aria-label'?: string;
  /** Shown when a query matches nothing. */
  emptyText?: string;
}

/** Must match `--menu-exit-dur` in tokens.css. */
const MENU_EXIT_MS = 140;
/** Only for the frame before the popup has been laid out and measured. */
const MENU_H_FALLBACK = 288;

/** Case-insensitive substring, over label and hint both. */
function matches(option: SelectOption, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return `${option.label} ${option.hint ?? ''}`.toLowerCase().includes(needle);
}

/**
 * The matched run of characters, drawn in brand colour.
 *
 * Without it a narrowed list is just a shorter list, and on a near-miss — two
 * options left, one matching only in the hint — there is nothing on screen
 * saying why either survived.
 */
function Highlight({ text, query }: { text: string; query: string }) {
  const needle = query.trim().toLowerCase();
  if (!needle) return <>{text}</>;
  const at = text.toLowerCase().indexOf(needle);
  if (at < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, at)}
      <mark className="select-match">{text.slice(at, at + needle.length)}</mark>
      {text.slice(at + needle.length)}
    </>
  );
}

export function SelectField({
  value,
  onChange,
  options,
  label,
  placeholder = '—',
  disabled = false,
  id,
  className = '',
  'aria-label': ariaLabel,
  emptyText = 'No matches',
}: SelectFieldProps) {
  const generatedId = useId();
  const fieldId = id ?? `select-${generatedId}`;
  const listId = `${fieldId}-listbox`;

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);

  const wrapRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  // Kept mounted through its exit so the popup can leave rather than vanish.
  const menuMounted = useExitDelay(open, MENU_EXIT_MS);
  const { dropUp, maxHeight } = useFlipPlacement(wrapRef, listRef, open, {
    fallbackHeight: MENU_H_FALLBACK,
  });

  const selected = useMemo(() => options.find((o) => o.value === value), [options, value]);
  const hasIcons = useMemo(() => options.some((o) => o.icon), [options]);
  const visible = useMemo(() => options.filter((o) => matches(o, query)), [options, query]);

  const close = useCallback((restoreFocus: boolean) => {
    setOpen(false);
    setQuery('');
    if (restoreFocus) inputRef.current?.focus();
  }, []);

  const commit = useCallback(
    (option: SelectOption) => {
      onChange(option.value);
      close(true);
    },
    [close, onChange],
  );

  const openMenu = useCallback(() => {
    if (disabled) return;
    setQuery('');
    // Land on the current value rather than the top of the list, so opening and
    // pressing Enter is a no-op instead of a silent change.
    setActiveIndex(Math.max(0, options.findIndex((o) => o.value === value)));
    setOpen(true);
  }, [disabled, options, value]);

  // A filtered list can be shorter than where the cursor was.
  useEffect(() => {
    setActiveIndex((current) => Math.min(current, Math.max(0, visible.length - 1)));
  }, [visible.length]);

  // Keyboard navigation has to reach past the popup's own scroll.
  useEffect(() => {
    if (!open) return;
    const row = listRef.current?.querySelector('[data-active="true"]');
    if (row instanceof HTMLElement) row.scrollIntoView({ block: 'nearest' });
  }, [open, activeIndex, visible.length]);

  /* Pointerdown, not click: a click on another control fires after that control
     has already taken focus, and closing on the later event let a second
     dropdown open while this one was still on screen. */
  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) close(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [open, close]);

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    switch (event.key) {
      case 'ArrowDown':
      case 'ArrowUp': {
        event.preventDefault();
        if (!open) {
          openMenu();
          return;
        }
        if (visible.length === 0) return;
        const step = event.key === 'ArrowDown' ? 1 : -1;
        // Wraps: a list this short is faster to reach by going the other way
        // than by holding the key against a stop.
        setActiveIndex((i) => (i + step + visible.length) % visible.length);
        return;
      }
      case 'Home':
      case 'End': {
        if (!open) return;
        event.preventDefault();
        setActiveIndex(event.key === 'Home' ? 0 : visible.length - 1);
        return;
      }
      case 'Enter': {
        if (!open) return;
        // Only swallowed while the popup is open — otherwise this would eat the
        // Enter that submits the form the field sits in.
        event.preventDefault();
        const option = visible[activeIndex];
        if (option) commit(option);
        return;
      }
      case 'Escape': {
        if (!open) return;
        // Stopped as well as prevented: this field lives inside the review
        // dialog, whose own Escape handler is on `window` and would close the
        // whole case behind the dropdown the nurse was dismissing.
        event.preventDefault();
        event.stopPropagation();
        close(true);
        return;
      }
      case 'Tab': {
        // Let focus leave; just do not leave a popup behind it.
        if (open) close(false);
        return;
      }
      default: {
        /* Type-to-open. The field is read-only while closed — it is showing the
           selected label, not the query, so a keystroke landing in it would
           append to that label and search for "OPD General Practicei". Taking
           the character here instead makes the first keystroke the whole query,
           which is what someone typing at a closed dropdown means. `setOpen`
           directly rather than `openMenu`, which would clear it. */
        if (open || disabled) return;
        if (event.key.length !== 1 || event.metaKey || event.ctrlKey || event.altKey) return;
        event.preventDefault();
        setQuery(event.key);
        setActiveIndex(0);
        setOpen(true);
      }
    }
  }

  return (
    <div className={`select-field ${className}`} ref={wrapRef}>
      {label && (
        <label htmlFor={fieldId} className="field-label">
          {label}
        </label>
      )}
      {/* The slot is reserved for the *current* selection's mark, not for the
          fact that some option somewhere has one. Reserving it unconditionally
          indented "All levels" by 2.75rem while its neighbours in the same
          toolbar started at the normal field padding, so one control in a row
          of three read as centred. */}
      <div className={`select-control ${selected?.icon ? 'has-icon' : ''}`}>
        {/* Closed *or* open: while the list is being narrowed the placeholder
            still shows the current selection, so the mark stays true. */}
        {selected?.icon && (
          <span className="select-adornment" aria-hidden="true">
            {selected.icon}
          </span>
        )}
        <input
          id={fieldId}
          ref={inputRef}
          type="text"
          role="combobox"
          autoComplete="off"
          spellCheck={false}
          disabled={disabled}
          aria-label={ariaLabel}
          aria-expanded={open}
          aria-controls={open ? listId : undefined}
          aria-autocomplete="list"
          aria-activedescendant={
            open && visible[activeIndex] ? `${listId}-${activeIndex}` : undefined
          }
          /* Closed, this shows the selection; open, it shows what is being typed
             and demotes the selection to the placeholder — so the current value
             stays legible while the list is being narrowed. */
          value={open ? query : selected?.label ?? ''}
          placeholder={open ? selected?.label ?? placeholder : placeholder}
          readOnly={!open}
          onChange={(event) => {
            setQuery(event.target.value);
            setActiveIndex(0);
          }}
          /* Click toggles, and focus deliberately does not open. Tabbing through
             a form should not leave a trail of popped-open dropdowns behind it —
             which is also how a native select behaves, and the reason keyboard
             users get ArrowDown and type-to-open instead. */
          onMouseDown={(event) => {
            if (disabled) return;
            if (open) {
              // Must not re-open on the focus that follows the click.
              event.preventDefault();
              close(true);
            } else {
              openMenu();
            }
          }}
          onKeyDown={handleKeyDown}
          className="field-input select-input"
        />
        <CaretDown
          size={16}
          weight="bold"
          aria-hidden="true"
          className={`select-caret ${open ? 'is-open' : ''}`}
        />
      </div>

      {menuMounted && (
        <ul
          id={listId}
          role="listbox"
          ref={listRef}
          /* On its way out it is still painted but no longer part of the
             control: `menuMounted` outlives `open` by the length of the exit,
             and a listbox left in the accessibility tree for that 140ms is one
             a screen reader can be told about after the field has already
             reported itself collapsed. */
          aria-hidden={open ? undefined : true}
          data-leaving={open ? undefined : 'true'}
          data-placement={dropUp ? 'top' : 'bottom'}
          style={{ maxHeight: Math.min(maxHeight ?? MENU_H_FALLBACK, MENU_H_FALLBACK) }}
          className="select-menu scroll-slim"
        >
          {visible.length === 0 ? (
            <li className="select-empty">{emptyText}</li>
          ) : (
            visible.map((option, index) => {
              const isSelected = option.value === value;
              const isActive = index === activeIndex;
              return (
                <li
                  key={option.value}
                  id={`${listId}-${index}`}
                  role="option"
                  aria-selected={isSelected}
                  data-active={isActive ? 'true' : undefined}
                  /* Delay compounds down the list, so the options arrive as a
                     run rather than a block. Capped so a long list does not make
                     the last row wait on the first thirty. */
                  style={{ '--select-option-delay': `${Math.min(index, 8) * 18}ms` } as CSSProperties}
                  // Mouse *move*, not enter: with the pointer resting over the
                  // list, opening the popup under it would otherwise steal the
                  // active row away from the keyboard before a key was pressed.
                  onMouseMove={() => setActiveIndex(index)}
                  // Down rather than click, so the input never blurs first.
                  onMouseDown={(event) => {
                    event.preventDefault();
                    commit(option);
                  }}
                  className={`select-option ${isActive ? 'is-active' : ''}`}
                >
                  {hasIcons && (
                    <span className="select-option-icon" aria-hidden="true">
                      {option.icon}
                    </span>
                  )}
                  <span className="select-option-text">
                    <Highlight text={option.label} query={query} />
                    {option.hint && (
                      <span className="select-option-hint">
                        <Highlight text={option.hint} query={query} />
                      </span>
                    )}
                  </span>
                  {isSelected && (
                    <Check size={16} weight="bold" aria-hidden="true" className="select-tick" />
                  )}
                </li>
              );
            })
          )}
        </ul>
      )}
    </div>
  );
}

/** Build options from a list of plain strings, with an optional relabeller. */
export function toOptions(
  values: readonly string[],
  label?: (value: string) => string,
): SelectOption[] {
  return values.map((value) => ({ value, label: label ? label(value) : value }));
}
