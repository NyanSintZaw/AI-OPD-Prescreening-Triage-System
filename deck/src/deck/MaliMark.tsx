import { useEffect, useState } from 'react';
import { NongMali } from '../design-system/components/NongMali';
import { useDeckMotionContext } from './motionContext';

export type MarkMotion = 'nongShowreel' | 'nongWaveHello' | 'nongHeartbeat' | 'nongExplode' | 'nongBounce';

/**
 * Nong Mali, sized, running one of her attract loops.
 *
 * Two things every placement has to get right, which is why they live here
 * rather than in each slide:
 *
 *   - The stage is roughly twice the mark. The attract loops throw expanding
 *     rings and jasmine petals into the mark's PARENT as DOM nodes, so a tight
 *     or clipping parent silently eats half the animation.
 *   - Under reduced motion the loop is not started at all — the mark then
 *     renders its authored resting state, which is correct by construction and
 *     better than any pose we could freeze it into ourselves.
 *
 * Pass `cycle` to move through several acts instead of looping one. The mark is
 * keyed on the current motion so it remounts and replays cleanly; `playMark`
 * resets the mark before every run, so switching mid-flight is safe by design.
 *
 * She belongs to greeting moments — the cover and the closing slide. Not
 * decoration on a table.
 */
export function MaliMark({
  size,
  motion = 'nongShowreel',
  cycle,
  intervalMs = 8000,
  className,
}: {
  size: number;
  motion?: MarkMotion;
  /** Play these in turn rather than looping `motion`. */
  cycle?: MarkMotion[];
  intervalMs?: number;
  className?: string;
}) {
  const deckMotion = useDeckMotionContext();
  const flat = deckMotion?.flat ?? false;
  const [step, setStep] = useState(0);

  useEffect(() => {
    /* No cycling under reduced motion — the mark holds its resting state. */
    if (flat || !cycle || cycle.length < 2) return;
    const id = window.setInterval(() => setStep((n) => n + 1), intervalMs);
    return () => window.clearInterval(id);
  }, [flat, cycle, intervalMs]);

  const current = cycle?.length ? cycle[step % cycle.length] : motion;
  const stage = Math.round(size * 2);

  return (
    <span
      className={`d-mark-stage${className ? ` ${className}` : ''}`}
      style={{ width: stage, height: stage }}
    >
      <NongMali key={current} size={size} motion={flat ? undefined : current} />
    </span>
  );
}
