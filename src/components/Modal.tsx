import { useEffect, type ReactNode } from 'react';
import { Button } from './Button';

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  /** Footer actions — usually a secondary + primary Button. */
  actions?: ReactNode;
  width?: number;
}
/** Centered dialog. Enters scale(.96)→1 over 300ms; Escape closes. Use only when the task needs protected focus. */
export function Modal({ open, onClose, title, children, actions, width = 480 }: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="mali-modal__backdrop" onClick={onClose}>
      <div className="mali-modal" role="dialog" aria-modal="true" aria-labelledby="mali-modal-title" style={{ width }} onClick={(e) => e.stopPropagation()}>
        <header className="mali-modal__head"><h2 id="mali-modal-title">{title}</h2>
          <Button variant="ghost" size="sm" aria-label="Close" onClick={onClose}>×</Button></header>
        <div className="mali-modal__body">{children}</div>
        {actions && <footer className="mali-modal__foot">{actions}</footer>}
      </div>
    </div>
  );
}
