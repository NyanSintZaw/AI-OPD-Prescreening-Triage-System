import { useEffect, useState, type ReactNode } from 'react';
import { animate, useReducedMotion } from 'framer-motion';

interface StatCounterProps {
  value: number;
  label: string;
  icon: ReactNode;
  /** Tile accent — each datapoint gets its own hue so the strip isn't uniform. */
  accent?: 'blue' | 'green' | 'violet' | 'amber';
}

/**
 * Compact horizontal stat tile (icon | count + label) with a count-up tween
 * when the value changes. Snaps immediately under reduced motion.
 */
export function StatCounter({ value, label, icon, accent = 'blue' }: StatCounterProps) {
  const reduce = useReducedMotion();
  const [display, setDisplay] = useState(reduce ? value : 0);

  useEffect(() => {
    if (reduce) {
      setDisplay(value);
      return;
    }
    const controls = animate(display, value, {
      duration: 1,
      ease: 'easeOut',
      onUpdate: (v) => setDisplay(Math.round(v)),
    });
    return () => controls.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, reduce]);

  return (
    <div className={`k-stat k-stat--${accent}`}>
      <span className="k-stat-icon" aria-hidden="true">
        {icon}
      </span>
      <span className="k-stat-body">
        <span className="k-stat-value">{display.toLocaleString()}</span>
        <span className="k-stat-label">{label}</span>
      </span>
    </div>
  );
}
