import { useReducedMotion } from 'framer-motion';
import { useState } from 'react';
import {
  flatRevealVariants,
  flatSlideVariants,
  revealVariants,
  slideVariants,
} from './motion';

/**
 * Motion state for the whole deck, plus the escape hatch.
 *
 * The accessibility case for honouring prefers-reduced-motion is the usual
 * one. The PRESENTING case is sharper: a Windows laptop with "Animation
 * effects" switched off, or an RDP session, will silently flatten the entire
 * cinematic deck five minutes before you go on. So the preference is
 * respected, surfaced loudly in the notes panel and on the cover, and `M`
 * overrides it for the length of the talk.
 */
export function useDeckMotion() {
  const prefersReduced = useReducedMotion();
  const [forced, setForced] = useState(false);
  const flat = Boolean(prefersReduced) && !forced;

  return {
    /** True when motion is suppressed. Content must still be complete. */
    flat,
    /** True when the OS asked for reduced motion, whether or not it is forced. */
    prefersReduced: Boolean(prefersReduced),
    forced,
    toggleForced: () => setForced((f) => !f),
    slide: flat ? flatSlideVariants : slideVariants,
    reveal: flat ? flatRevealVariants : revealVariants,
  };
}

export type DeckMotion = ReturnType<typeof useDeckMotion>;
