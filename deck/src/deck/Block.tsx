import { motion } from 'framer-motion';
import type { ReactNode } from 'react';
import { useReveal } from './motionContext';

/**
 * Every block inside every layout wraps in this.
 *
 * The slide's own variants set `staggerChildren`, so ordering is positional —
 * a block reveals because of where it sits, not because someone tuned a delay
 * for it. That is the whole reason no layout in this deck contains a number of
 * milliseconds.
 */
export function Block({
  children,
  className,
  as = 'div',
}: {
  children: ReactNode;
  className?: string;
  as?: 'div' | 'section' | 'footer' | 'aside' | 'ul' | 'ol' | 'p';
}) {
  const reveal = useReveal();
  const M = motion[as];
  return (
    <M className={className} variants={reveal}>
      {children}
    </M>
  );
}
