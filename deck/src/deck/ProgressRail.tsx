import { PITCH_SLIDES } from '../content/slides';
import type { SlideId } from '../content/types';

/**
 * A hairline across the foot of the stage, one segment per slide, each as wide
 * as its budget in PITCH_DECK. The cover is excluded — it plays while the room
 * settles and is not on the clock.
 *
 * The audience sees position. They do not see the clock: the mm:ss readout
 * lives in the notes panel, because a room that can watch you fall behind
 * watches that instead of the pitch.
 *
 * Neither is the appendix. Those three sit after Questions and are reached only
 * if the room asks, so the rail keeps measuring exactly the part of the pitch
 * that is timed — and standing on one reads as past the end, not as nowhere.
 *
 * It takes an id rather than an index on purpose: the appendix is a suffix
 * today, so a PITCH_SLIDES index and a SLIDES index happen to agree, and a
 * component that leaned on that would start lying the day someone puts an
 * appendix slide in the middle.
 */
export function ProgressRail({
  currentId,
  elapsedInSlide,
}: {
  currentId: SlideId;
  elapsedInSlide: number;
}) {
  const timed = PITCH_SLIDES.map((s, i) => ({ slide: s, i })).filter(({ slide }) => slide.budgetSec > 0);
  /* An appendix slide is not in this list. Treat it as past the last segment
     rather than as -1, or the rail empties itself in front of the room the
     moment the presenter steps past Q&A. */
  const found = PITCH_SLIDES.findIndex((s) => s.id === currentId);
  const currentIndex = found === -1 ? PITCH_SLIDES.length : found;

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
