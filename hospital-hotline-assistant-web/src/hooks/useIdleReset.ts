import { useCallback, useEffect, useRef, useState } from 'react';

interface UseIdleResetOptions {
  /** Whether the idle watchdog is armed (e.g. false on the home screen). */
  enabled: boolean;
  /** Idle time before the "are you still there?" prompt appears (ms). */
  warnAfterMs?: number;
  /** Extra grace after the prompt before we auto-reset (ms). */
  graceMs?: number;
  /** Called when the patient is deemed gone — reset the booth to home. */
  onReset: () => void;
}

/**
 * Booth inactivity watchdog. Any pointer/key/touch activity resets the timer.
 * After `warnAfterMs` of silence it surfaces a countdown prompt; if still
 * untouched after `graceMs` more it fires `onReset` so the next visitor starts
 * fresh. Returns the warning state + a `stayActive` acknowledger for the
 * "I'm still here" button.
 */
export function useIdleReset({
  enabled,
  warnAfterMs = 45000,
  graceMs = 15000,
  onReset,
}: UseIdleResetOptions) {
  const [warning, setWarning] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(Math.ceil(graceMs / 1000));
  const warnTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const graceTimer = useRef<ReturnType<typeof setInterval> | undefined>(undefined);
  const onResetRef = useRef(onReset);
  onResetRef.current = onReset;

  const clearAll = useCallback(() => {
    clearTimeout(warnTimer.current);
    clearInterval(graceTimer.current);
  }, []);

  const arm = useCallback(() => {
    clearAll();
    setWarning(false);
    if (!enabled) return;
    warnTimer.current = setTimeout(() => {
      setWarning(true);
      let remaining = Math.ceil(graceMs / 1000);
      setSecondsLeft(remaining);
      graceTimer.current = setInterval(() => {
        remaining -= 1;
        setSecondsLeft(remaining);
        if (remaining <= 0) {
          clearAll();
          setWarning(false);
          onResetRef.current();
        }
      }, 1000);
    }, warnAfterMs);
  }, [clearAll, enabled, graceMs, warnAfterMs]);

  // `stayActive` is called by the "I'm still here" button.
  const stayActive = useCallback(() => arm(), [arm]);

  useEffect(() => {
    if (!enabled) {
      clearAll();
      setWarning(false);
      return;
    }
    arm();
    const onActivity = () => {
      // Ignore activity while the warning modal is up — the modal has its own
      // explicit buttons so a stray touch doesn't silently cancel the reset.
      if (!warning) arm();
    };
    const events: Array<keyof WindowEventMap> = [
      'pointerdown',
      'keydown',
      'touchstart',
      'mousemove',
    ];
    events.forEach((e) => window.addEventListener(e, onActivity, { passive: true }));
    return () => {
      events.forEach((e) => window.removeEventListener(e, onActivity));
      clearAll();
    };
  }, [enabled, arm, clearAll, warning]);

  return { warning, secondsLeft, stayActive };
}
