/**
 * Deck motion. Framer Motion cannot read a CSS custom property, so the design
 * system's easings are restated here once, with the token they mirror named in
 * a comment. If effects.css changes, change these.
 *
 * Two deliberate departures from mali-design-system/docs/guides/motion.md,
 * both documented in deck/CLAUDE.md so nobody "fixes" them:
 *
 *   - The 420ms slide enter. The guide's 300ms ceiling governs a transition
 *     the user is waiting on after their own click. A slide change is a
 *     presentational beat read from eight metres, where 300ms reads as a snap.
 *   - The EscalationGate spring. The guide forbids overshoot on feedback;
 *     that visual is a depiction of a clinical escalation, and the snap is
 *     what sells "immediately, mid-interview".
 *
 * More broadly: the guide restrains motion in the PRODUCT. A deck is a
 * different surface running a louder budget on the same tokens.
 */
import type { Variants } from 'framer-motion';

/** = --ease-enter, cubic-bezier(.16, 1, .3, 1). */
export const EASE_ENTER = [0.16, 1, 0.3, 1] as const;
/** = --ease-exit, cubic-bezier(.4, 0, 1, 1). */
export const EASE_EXIT = [0.4, 0, 1, 1] as const;

/** A deck moves horizontally. `custom` carries the direction from useDeckNav. */
export const slideVariants: Variants = {
  enter: (dir: 1 | -1) => ({ opacity: 0, x: dir * 64, scale: 0.985 }),
  center: {
    opacity: 1,
    x: 0,
    scale: 1,
    transition: {
      duration: 0.42,
      ease: EASE_ENTER,
      when: 'beforeChildren',
      delayChildren: 0.12,
      staggerChildren: 0.08,
    },
  },
  exit: (dir: 1 | -1) => ({
    opacity: 0,
    x: dir * -40,
    scale: 0.995,
    /* Exits are faster than enters — the guide's rule, and it holds here. */
    transition: { duration: 0.2, ease: EASE_EXIT },
  }),
};

/**
 * Every block inside every layout wraps in this. The parent's staggerChildren
 * does the sequencing, so no layout ever hand-tunes a delay.
 */
export const revealVariants: Variants = {
  enter: { opacity: 0, y: 18 },
  center: { opacity: 1, y: 0, transition: { duration: 0.5, ease: EASE_ENTER } },
  exit: { opacity: 0, y: -8, transition: { duration: 0.16, ease: EASE_EXIT } },
};

/* Flattened counterparts. A motion preference suppresses TRANSITION, never
   CONTENT: nothing below hides anything, it only stops it moving. */
export const flatSlideVariants: Variants = {
  enter: { opacity: 0 },
  center: { opacity: 1, transition: { duration: 0, when: 'beforeChildren' } },
  exit: { opacity: 0, transition: { duration: 0 } },
};

export const flatRevealVariants: Variants = {
  enter: { opacity: 1, y: 0 },
  center: { opacity: 1, y: 0, transition: { duration: 0 } },
  exit: { opacity: 1, y: 0, transition: { duration: 0 } },
};
