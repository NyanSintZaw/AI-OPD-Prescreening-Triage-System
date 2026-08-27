import { createContext, useContext, type ReactNode } from 'react';
import type { Variants } from 'framer-motion';
import { revealVariants } from './motion';
import type { DeckMotion } from './useDeckMotion';

/**
 * Deck-wide motion state, in context rather than threaded through props.
 *
 * Every reveal in the deck resolves its variants through here, so flattening
 * the deck for reduced motion is one switch at the root rather than a prop
 * every layout and visual has to remember to pass down. A visual that forgets
 * it would keep animating on a machine that asked for stillness.
 */
const MotionContext = createContext<DeckMotion | null>(null);

export function DeckMotionProvider({
  value,
  children,
}: {
  value: DeckMotion;
  children: ReactNode;
}) {
  return <MotionContext.Provider value={value}>{children}</MotionContext.Provider>;
}

export function useDeckMotionContext(): DeckMotion | null {
  return useContext(MotionContext);
}

/** The reveal variants for the current motion state. Falls back to the full set. */
export function useReveal(): Variants {
  return useContext(MotionContext)?.reveal ?? revealVariants;
}

/** True when motion is suppressed — visuals render their end state instead. */
export function useFlat(): boolean {
  return useContext(MotionContext)?.flat ?? false;
}
