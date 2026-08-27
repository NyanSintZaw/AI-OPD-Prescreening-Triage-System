import { useEffect, useRef, useState } from 'react';

/**
 * The rehearsal clock. PITCH_DECK asks for three end-to-end run-throughs, and
 * a deck that cannot time itself makes that an exercise in phone-watching.
 */
export function useTimer() {
  const [running, setRunning] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const startedAt = useRef<number | null>(null);
  const base = useRef(0);

  useEffect(() => {
    if (!running) return;
    startedAt.current = performance.now();
    const id = window.setInterval(() => {
      setElapsed(base.current + (performance.now() - (startedAt.current ?? 0)) / 1000);
    }, 200);
    return () => {
      base.current = base.current + (performance.now() - (startedAt.current ?? 0)) / 1000;
      window.clearInterval(id);
    };
  }, [running]);

  return {
    elapsed,
    running,
    toggle: () => setRunning((r) => !r),
    reset: () => {
      setRunning(false);
      base.current = 0;
      setElapsed(0);
    },
  };
}

export function mmss(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}
