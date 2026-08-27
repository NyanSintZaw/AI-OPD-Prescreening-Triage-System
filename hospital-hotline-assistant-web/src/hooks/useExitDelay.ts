import { useEffect, useState } from 'react';


/**
 * Keeps something mounted for the length of its exit animation after it stops
 * being wanted, so it can leave rather than vanish.
 *
 * Returns `active || stillLeaving` — the `active ||` matters on the frame where
 * it has just been switched back on, before the effect has run.
 */
export function useExitDelay(active: boolean, exitMs: number): boolean {
  const [mounted, setMounted] = useState(active);

  useEffect(() => {
    if (active) {
      setMounted(true);
      return undefined;
    }
    const timer = window.setTimeout(() => setMounted(false), exitMs);
    return () => window.clearTimeout(timer);
  }, [active, exitMs]);

  return active || mounted;
}
