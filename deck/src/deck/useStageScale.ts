import { useEffect, useState } from 'react';

/**
 * The stage is a fixed 1920x1080 logical canvas, uniformly scaled to fit.
 *
 * Fixed rather than fluid, and this is the deck's most consequential layout
 * decision. The kiosk uses clamp() because it runs on one known screen
 * forever; a deck runs once, on a projector nobody has measured. With clamp(),
 * a Thai headline breaks in a different place at 1366x768 than on the laptop
 * it was rehearsed on, and you find out in front of the room. Scaling a fixed
 * canvas means what you rehearsed is pixel-proportionally what projects.
 */
export function useStageScale(w = 1920, h = 1080): number {
  const [scale, setScale] = useState(1);

  useEffect(() => {
    const fit = () => setScale(Math.min(window.innerWidth / w, window.innerHeight / h));
    fit();
    window.addEventListener('resize', fit);
    return () => window.removeEventListener('resize', fit);
  }, [w, h]);

  return scale;
}
