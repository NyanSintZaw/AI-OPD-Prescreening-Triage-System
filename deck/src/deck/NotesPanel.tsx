import { FLOW_SLIDES } from '../content/slides';
import type { Slide } from '../content/types';
import { mmss } from './useTimer';

/**
 * The presenter's half of the screen, docked under the letterboxed stage.
 *
 * Everything PITCH_DECK says a presenter needs and an audience must not see:
 * the notes, the TH/EN badge, what the other presenter is doing, the budget,
 * the clock, and the next headline so the handoff is never improvised.
 */
export function NotesPanel({
  slide,
  index,
  elapsed,
  elapsedInSlide,
  timerRunning,
  reducedMotionWarning,
}: {
  slide: Slide;
  index: number;
  elapsed: number;
  elapsedInSlide: number;
  timerRunning: boolean;
  reducedMotionWarning: boolean;
}) {
  const next = FLOW_SLIDES[index + 1];
  const total = FLOW_SLIDES.reduce((n, s) => n + s.budgetSec, 0);
  const over = slide.budgetSec > 0 && elapsedInSlide > slide.budgetSec;

  return (
    <aside className="d-notes">
      <header className="d-notes-head">
        <span className={`d-badge d-badge--${slide.presenter.toLowerCase()}`}>
          {slide.presenter}
        </span>
        <span className="d-notes-title">
          {slide.number ? `Slide ${slide.number}` : slide.layout === 'hold' ? 'Hold screen' : 'Cover'}
          {' · '}
          {slide.headline.en}
        </span>
        <span className={`d-notes-clock${over ? ' is-over' : ''}`}>
          {mmss(elapsedInSlide)}
          {slide.budgetSec > 0 && <em> / {mmss(slide.budgetSec)}</em>}
        </span>
        <span className="d-notes-total">
          {timerRunning ? '' : 'paused '}
          {mmss(elapsed)} / {mmss(total)}
        </span>
      </header>

      {reducedMotionWarning && (
        <p className="d-notes-warn">
          Reduced motion is on for this machine — the deck is flat. Press M to force motion.
        </p>
      )}

      {slide.coPresenter && <p className="d-notes-co">Other presenter: {slide.coPresenter}</p>}

      <ul className="d-notes-list">
        {slide.notes.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>

      <footer className="d-notes-foot">
        {slide.source && <span className="d-notes-source">{slide.source}</span>}
        {next && <span className="d-notes-next">Next: {next.headline.en}</span>}
      </footer>
    </aside>
  );
}
