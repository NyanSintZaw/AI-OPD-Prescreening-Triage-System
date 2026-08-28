import { useEffect, useState } from 'react';

/**
 * The stage is a 1920-wide logical canvas, uniformly scaled to fit.
 *
 * Fixed width rather than fluid, and this is the deck's most consequential
 * layout decision. The kiosk uses clamp() because it runs on one known screen
 * forever; a deck runs once, on a projector nobody has measured. With clamp(),
 * a Thai headline breaks in a different place at 1366x768 than on the laptop
 * it was rehearsed on, and you find out in front of the room. Scaling a fixed
 * canvas means what you rehearsed is pixel-proportionally what projects.
 *
 * The canvas HEIGHT does flex, up to 1.6x. Line breaking is a function of
 * width alone, so growing the canvas downward costs nothing the rehearsal
 * relies on — and it buys the whole screen. A 16:10 laptop or a 4:3 projector
 * would otherwise letterbox a 16:9 stage in grey; instead the stage's own
 * paper fills the panel. The slide inside stays exactly `h` tall and centred
 * (see `.deck-slide` in deck.css), so no layout moves.
 */
export function useStageScale(w = 1920, h = 1080): { scale: number; height: number } {
  const [stage, setStage] = useState({ scale: 1, height: h });

  useEffect(() => {
    const fit = () => {
      const scale = Math.min(window.innerWidth / w, window.innerHeight / h);
      setStage({ scale, height: Math.min(window.innerHeight / scale, h * 1.6) });
    };
    fit();
    window.addEventListener('resize', fit);
    return () => window.removeEventListener('resize', fit);
  }, [w, h]);

  return stage;
}
