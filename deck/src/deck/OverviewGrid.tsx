import { SLIDES } from '../content/slides';
import type { Slide } from '../content/types';
import { mmss } from './useTimer';

/**
 * Every slide at a glance. Thumbnails are the real headline and the real
 * metadata rather than screenshots, so the grid cannot go stale — a deck whose
 * overview lies is worse than one without an overview.
 */
export function OverviewGrid({
  currentId,
  onPick,
  onClose,
}: {
  currentId: string;
  onPick: (id: Slide['id']) => void;
  onClose: () => void;
}) {
  return (
    <div className="d-overlay d-overlay--grid" onClick={onClose} role="presentation">
      <div className="d-grid" onClick={(e) => e.stopPropagation()} role="presentation">
        {SLIDES.map((s, i) => (
          <button
            key={s.id}
            type="button"
            className={`d-cell${s.id === currentId ? ' is-current' : ''} d-cell--${s.section}${
              s.appendix ? ' d-cell--appendix' : ''
            }`}
            onClick={() => {
              onPick(s.id);
              onClose();
            }}
          >
            <span className="d-cell-meta">
              <span className={`d-badge d-badge--${s.presenter.toLowerCase()}`}>{s.presenter}</span>
              <span>{s.number ? `${s.number}` : s.layout === 'hold' ? '—' : '–'}</span>
              {s.budgetSec > 0 && <span className="d-cell-budget">{mmss(s.budgetSec)}</span>}
            </span>
            {/* An English-lead slide has no Thai title to show. */}
            <span className="d-cell-th" lang={s.headline.th ? 'th' : 'en'}>
              {s.headline.th ?? s.headline.en}
            </span>
            <span className="d-cell-en" lang="en">
              {s.headline.en}
            </span>
            <span className="d-cell-index">{i}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
