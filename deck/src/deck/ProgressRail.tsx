import { SLIDES } from '../content/slides';

/**
 * A hairline across the foot of the stage, one segment per slide, each as wide
 * as its budget in PITCH_DECK. The cover is excluded — it plays while the room
 * settles and is not on the clock.
 *
 * The audience sees position. They do not see the clock: the mm:ss readout
 * lives in the notes panel, because a room that can watch you fall behind
 * watches that instead of the pitch.
 */
export function ProgressRail({
  currentIndex,
  elapsedInSlide,
}: {
  currentIndex: number;
  elapsedInSlide: number;
}) {
  const timed = SLIDES.map((s, i) => ({ slide: s, i })).filter(({ slide }) => slide.budgetSec > 0);

  return (
    <div className="d-rail" aria-hidden="true">
      {timed.map(({ slide, i }, n) => {
        const isPast = i < currentIndex;
        const isNow = i === currentIndex;
        const ratio = isNow ? Math.min(1.4, elapsedInSlide / slide.budgetSec) : 0;
        const over = ratio >= 1.25 ? 'danger' : ratio >= 1 ? 'warn' : 'ok';
        const prevSection = n > 0 ? timed[n - 1].slide.section : null;

        return (
          <div
            key={slide.id}
            className={`d-rail-seg${prevSection && prevSection !== slide.section ? ' is-boundary' : ''}`}
            style={{ flexGrow: slide.budgetSec }}
          >
            <span
              className={`d-rail-fill is-${over}`}
              style={{ transform: `scaleX(${isPast ? 1 : Math.min(1, ratio)})` }}
            />
          </div>
        );
      })}
    </div>
  );
}
