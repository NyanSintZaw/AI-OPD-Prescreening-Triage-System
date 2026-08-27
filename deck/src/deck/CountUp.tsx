import { animate } from 'framer-motion';
import { useEffect, useRef, useState } from 'react';
import { useFlat } from './motionContext';

/**
 * A number that arrives rather than appears.
 *
 * Same shape as the kiosk attract screen's AnimatedNumber — animate() with an
 * easeOut, stopped on cleanup so a fast arrow through the deck never leaves a
 * counter running against an unmounted slide. Under reduced motion it renders
 * its final value immediately: the point is the number, not the climb.
 */
export function CountUp({
  to,
  from = 0,
  duration = 0.9,
  delay = 0,
  locale = 'th-TH',
  prefix,
  suffix,
}: {
  to: number;
  from?: number;
  duration?: number;
  delay?: number;
  locale?: 'th-TH' | 'en-US';
  prefix?: string;
  suffix?: string;
}) {
  const flat = useFlat();
  const [value, setValue] = useState(flat ? to : from);
  const node = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (flat) {
      setValue(to);
      return;
    }
    setValue(from);
    const controls = animate(from, to, {
      duration,
      delay,
      ease: 'easeOut',
      onUpdate: (v) => setValue(v),
    });
    return () => controls.stop();
  }, [to, from, duration, delay, flat]);

  const rounded = Math.round(value);

  return (
    <span ref={node} className="d-count">
      {prefix}
      {rounded.toLocaleString(locale)}
      {suffix}
    </span>
  );
}
