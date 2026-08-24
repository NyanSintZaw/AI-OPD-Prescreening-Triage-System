import type { ReactNode } from 'react';
import { cx } from './cx';

export interface ToastProps {
  tone?: 'neutral' | 'success' | 'warning' | 'danger';
  title: string;
  description?: ReactNode;
  /** Optional single action (e.g. "Undo"). */
  action?: { label: string; onClick: () => void };
  onDismiss?: () => void;
}
/** Bottom-right notice. Same edge in and out; exit is faster than enter. */
export function Toast({ tone = 'neutral', title, description, action, onDismiss }: ToastProps) {
  return (
    <div className={cx('mali-toast', `mali-toast--${tone}`)} role="status">
      <i className="mali-toast__bar" aria-hidden="true" />
      <div className="mali-toast__text"><strong>{title}</strong>{description && <div className="mali-toast__desc">{description}</div>}</div>
      {action && <button type="button" className="mali-toast__action" onClick={action.onClick}>{action.label}</button>}
      {onDismiss && <button type="button" className="mali-toast__x" aria-label="Dismiss" onClick={onDismiss}>×</button>}
    </div>
  );
}
