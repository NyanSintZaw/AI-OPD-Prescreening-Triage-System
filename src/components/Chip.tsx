import type { ButtonHTMLAttributes } from 'react';
import { cx } from './cx';

export interface ChipProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  selected?: boolean;
  /** Shows an × and calls onRemove. */
  onRemove?: () => void;
  size?: 'md' | 'kiosk';
}
/** A selectable pill — symptom tags, quick answers on the kiosk. */
export function Chip({ selected, onRemove, size = 'md', className, children, ...rest }: ChipProps) {
  return (
    <button type="button" aria-pressed={selected} className={cx('mali-chip', `mali-chip--${size}`, selected && 'mali-chip--selected', className)} {...rest}>
      {children}
      {onRemove && <span role="button" aria-label="Remove" className="mali-chip__x" onClick={(e) => { e.stopPropagation(); onRemove(); }}>×</span>}
    </button>
  );
}
