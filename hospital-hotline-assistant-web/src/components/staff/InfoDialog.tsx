/**
 * A titled dialog on the shared staff shell.
 *
 * Same anatomy as the nurse's case dialog — head, identity, scrolling body,
 * backdrop button — so a popup opens the same way on every staff surface. It
 * exists because the third near-identical copy of that markup was about to be
 * written: the HIS record, a paired device's details, and the pairing wizard
 * are all "a titled card over a backdrop", differing only in width.
 *
 * `.dialog-card` is a fixed 78rem x 54rem so the case review does not resize
 * as its tabs change. Nothing here has tabs, so each size is as tall as its
 * content and no taller.
 *
 * It also owns its own exit. Its parents mount it conditionally, so it cannot
 * delay its own unmount — instead it flags itself leaving, lets the CSS run,
 * and calls the parent's `onClose` when the animation is over. Every caller
 * gets the close animation without knowing it exists.
 */


import { useEffect, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from '@phosphor-icons/react';
import { useDialogExit } from '../../hooks/useDialogExit';

export function InfoDialog({
  title,
  meta,
  size = 'sm',
  onClose,
  children,
}: {
  title: string;
  /** The line under the title — a code chip, a status chip, a timestamp. */
  meta?: ReactNode;
  /** `sm` for a ledger or a form; `md` where a table has to fit. */
  size?: 'sm' | 'md';
  onClose: () => void;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const { leaving, close } = useDialogExit(onClose);

  // Escape closes — a modal without it traps keyboard users.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [close]);

  return (
    <div className="dialog" role="dialog" aria-modal="true" aria-label={title}>
      {/* A real button, not a handler on a div: the backdrop is the escape
          hatch and has to be reachable without a pointer. */}
      <button
        type="button"
        className="dialog-backdrop"
        data-leaving={leaving || undefined}
        aria-label={t('close')}
        onClick={close}
      />
      <div
        className={`dialog-card info-dialog info-dialog-${size}`}
        data-leaving={leaving || undefined}
      >
        <header className="dialog-head">
          <div className="dialog-identity">
            <div>
              <h2>{title}</h2>
              {meta ? <p className="dialog-identity-meta">{meta}</p> : null}
            </div>
          </div>
          <button type="button" className="icon-btn" onClick={close} aria-label={t('close')}>
            <X size={20} aria-hidden="true" />
          </button>
        </header>
        <div className="dialog-body">{children}</div>
      </div>
    </div>
  );
}
