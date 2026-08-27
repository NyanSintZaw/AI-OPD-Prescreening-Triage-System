import { motion } from 'framer-motion';
import { FACTS } from '../content/facts';
import type { Slide } from '../content/types';
import { CountUp } from '../deck/CountUp';
import { EASE_ENTER } from '../deck/motion';
import { useFlat } from '../deck/motionContext';

type Stats = Extract<Slide, { layout: 'hero' }>['stats'];

/**
 * Slide 2's evidence: 11,624 encounters in a week, split into the ones that
 * already had somewhere to be and the ones that did not, and what that comes
 * to per day.
 *
 * The beats are sequenced so the spoken line has somewhere to land. The track
 * grows from the left; the walk-in block then grows from the RIGHT, so it
 * reads as arriving into the whole rather than the whole simply getting
 * longer. The counters are deliberately offset — 3,072 finishes about half a
 * second after 11,624, alone — and 440 lands last, by itself.
 *
 * Transforms and opacity only. Nothing here animates width.
 */
export function WalkinStats({ stats }: { stats: Stats }) {
  const flat = useFlat();

  const total = FACTS[stats.total.fact].value;
  const [left, right] = stats.split;
  const leftValue = FACTS[left.fact].value;
  const rightValue = FACTS[right.fact].value;
  const heroValue = FACTS[stats.hero.fact].value;

  /* Returns only motion props — never `style`. Spreading a style object here
     would clobber the `style` prop it is spread next to, which silently cost
     the walk-in segment its flex-grow and collapsed it to nothing. */
  const grow = (delay: number, duration: number) =>
    flat
      ? {}
      : {
          initial: { scaleX: 0 },
          animate: { scaleX: 1 },
          transition: { duration, delay, ease: EASE_ENTER },
        };

  return (
    <div className="d-stats">
      <div className="d-stats-total">
        <strong>
          <CountUp to={total} delay={flat ? 0 : 0.2} />
        </strong>
        <span className="d-stats-total-label" lang="th">
          {stats.total.label}
        </span>
        {/* Never animated: a source is not a flourish. */}
        <span className="d-stats-source" lang="th">
          {stats.source}
        </span>
      </div>

      <motion.div
        className="d-stats-bar"
        style={{ transformOrigin: 'left center' }}
        {...grow(0.3, 0.7)}
      >
        <div className="d-stats-seg d-stats-seg--had" style={{ flexGrow: leftValue }}>
          <strong>
            <CountUp to={leftValue} delay={flat ? 0 : 0.45} />
          </strong>
          <span lang="th">{left.label}</span>
        </div>

        {/* Grows from the RIGHT, so it reads as arriving into the whole
            rather than the whole simply getting longer. */}
        <motion.div
          className="d-stats-seg d-stats-seg--lost"
          style={{ flexGrow: rightValue, transformOrigin: 'right center' }}
          {...grow(0.7, 0.55)}
        >
          <strong>
            <CountUp to={rightValue} delay={flat ? 0 : 0.95} duration={1} />
          </strong>
          <span lang="th">{right.label}</span>
        </motion.div>
      </motion.div>

      <div className="d-stats-hero">
        <strong className="d-stats-hero-n">
          <CountUp to={heroValue} delay={flat ? 0 : 1.6} duration={1.1} />
        </strong>
        <span className="d-stats-hero-body">
          <span className="d-stats-hero-label" lang="th">
            {stats.hero.label}
          </span>
          <span className="d-stats-hero-sub" lang="en">
            {stats.hero.sub}
          </span>
        </span>
      </div>
    </div>
  );
}
