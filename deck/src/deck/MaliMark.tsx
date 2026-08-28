import { NongMali } from '../design-system/components/NongMali';
import type { ShowreelAct } from '../design-system/motion';
import { useDeckMotionContext } from './motionContext';

export type { ShowreelAct };

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
 * There is deliberately no cycling here. This component used to rotate through
 * a list of motions on an 8s interval, which cut acts off mid-flight and
 * replayed them in a fixed order. `nongShowreel` already sequences its acts
 * properly — random order, never the same act twice running, each played to
 * the length it reports — so a second scheduler on top of it could only be
 * worse. A slide that wants a different feel passes a different `motion`, and
 * `acts` chooses which of the showreel's four the mixer may draw from.
 *
 * She belongs to greeting moments — the cover and the closing slide. Not
 * decoration on a table.
 */
export function MaliMark({
  size,
  motion = 'nongShowreel',
  acts,
  className,
}: {
  size: number;
  motion?: MarkMotion;
  /** `nongShowreel` only — which acts the mixer may play. */
  acts?: ShowreelAct[];
  className?: string;
}) {
  const deckMotion = useDeckMotionContext();
  const flat = deckMotion?.flat ?? false;
  const stage = Math.round(size * 2);

  return (
    <span
      className={`d-mark-stage${className ? ` ${className}` : ''}`}
      style={{ width: stage, height: stage }}
    >
      <NongMali size={size} motion={flat ? undefined : motion} acts={acts} />
    </span>
  );
}
