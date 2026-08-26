import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * How long a dialog takes to leave — the design system's `--dur-exit`.
 *
 * A timeout cannot read a CSS custom property, so this is the JS half of a
 * pair that has to stay in step with `.dialog-card[data-leaving]` in
 * `staff.css`. Reduced motion zeroes the CSS but not this, and that is the
 * safe direction: the card is already invisible, it just unmounts 200ms later.
 */
export const DIALOG_EXIT_MS = 200;

/**
 * Lets a dialog leave instead of vanish.
 *
 * Every dialog in the staff portals is mounted from a piece of state in its
 * *parent*, so calling `onClose` on the click unmounts the card mid-frame and
 * the exit animation never runs. This flags the card leaving, lets the CSS
 * play, and calls `onClose` once nothing is on screen.
 *
 * ```tsx
 * const { leaving, close } = useDialogExit(onClose);
 * <div className="dialog-card" data-leaving={leaving || undefined}>
 * ```
 *
 * The guard matters: a backdrop click, the X and Escape all land here, and a
 * second press during the 200ms would queue a second unmount.
 */
export function useDialogExit(onClose: () => void) {
  const [leaving, setLeaving] = useState(false);
  const timer = useRef(0);

  const close = useCallback(() => {
    if (timer.current) return;
    setLeaving(true);
    timer.current = window.setTimeout(onClose, DIALOG_EXIT_MS);
  }, [onClose]);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  return { leaving, close };
}
