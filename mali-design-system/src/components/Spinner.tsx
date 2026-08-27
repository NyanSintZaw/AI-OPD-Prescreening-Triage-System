import { cx } from './cx';

export interface SpinnerProps { size?: number; className?: string; /** Accessible label. */ label?: string; }
/** Loading (data is on its way). For agent work use `Thinking`. */
export function Spinner({ size = 20, className, label = 'Loading' }: SpinnerProps) {
  return (
    <svg className={cx('mali-spinner', className)} width={size} height={size} viewBox="0 0 24 24" role="status" aria-label={label}>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.18" strokeWidth="2.5" fill="none" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" fill="none" />
    </svg>
  );
}

export interface ThinkingProps { /** Text next to the orbit, e.g. "MALI is listening". */ label?: string; size?: number; }
/** Agent work (MALI is extracting/deciding). A gold bead orbits the ring — drawn from the mark. */
export function Thinking({ label, size = 20 }: ThinkingProps) {
  return (
    <span className="mali-thinking" role="status" aria-live="polite">
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <ellipse cx="12" cy="12" rx="9" ry="5" transform="rotate(-35 12 12)" stroke="currentColor" strokeWidth="1.5" strokeOpacity="0.35" />
        <circle className="mali-thinking__bead" r="2.2" fill="var(--color-accent)" />
      </svg>
      {label && <span className="mali-thinking__label">{label}</span>}
    </span>
  );
}
