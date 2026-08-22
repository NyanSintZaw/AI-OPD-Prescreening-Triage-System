import type { HTMLAttributes } from 'react';
import { cx } from './cx';

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: 'neutral' | 'success' | 'info' | 'warning' | 'danger' | 'accent';
  /** MOPH triage level 1–5. Overrides `tone`. Nurse/admin only — never shown to patients. */
  level?: 1 | 2 | 3 | 4 | 5;
  /** Dot-only marker (for dense tables). */
  dot?: boolean;
}
const LEVEL_LABEL = { 1: 'Resuscitation', 2: 'Emergency', 3: 'Urgent', 4: 'Semi-urgent', 5: 'Non-urgent' } as const;

export function Badge({ tone = 'neutral', level, dot, className, children, ...rest }: BadgeProps) {
  return (
    <span className={cx('mali-badge', level ? `mali-badge--l${level}` : `mali-badge--${tone}`, dot && 'mali-badge--dot', className)} {...rest}>
      <i className="mali-badge__dot" aria-hidden="true" />
      {!dot && (children ?? (level ? `${level} · ${LEVEL_LABEL[level]}` : null))}
    </span>
  );
}
