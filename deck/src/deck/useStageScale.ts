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
 *
 * Below a point, scaling stops being an answer: the deck is now a link people
 * open on a phone, and a 1920 canvas on a 393px screen is a fifth of legible.
 * So this also reports a MODE, and `fluid` hands the slide to `fluid.css` to
 * reflow. Everything above the threshold keeps the rehearsed stage untouched —
 * see `deck/CLAUDE.md`, "Two modes".
 */
export type StageMode = 'stage' | 'fluid';

/* Below this scale the deck's body tier — 20-22 stage px — renders under 13
   CSS px, which is where Anuphan's Thai tone marks stop resolving. */
const LEGIBLE_SCALE = 0.62;
/* A desktop window dragged narrow. Deliberately BELOW 1024: a 4:3 projector
   at 1024x768 scales to 0.53 and so trips the scale test, and it is the exact
   panel the fixed stage exists for. It must stay on the stage, so width alone
   is never enough to force fluid above this. */
const NARROW = 900;

/**
 * `?mode=stage` / `?mode=fluid`, the escape hatch for the one machine the
 * heuristic cannot read: a venue laptop in tablet mode, no mouse attached,
 * driving a projector. It lives in the SEARCH string, before the hash, so it
 * survives every slide navigation for free — `…/?mode=stage#/problems`.
 */
function forcedMode(): StageMode | null {
  const m = new URLSearchParams(window.location.search).get('mode');
  return m === 'stage' || m === 'fluid' ? m : null;
}

export function useStageScale(
  w = 1920,
  h = 1080,
): { scale: number; height: number; mode: StageMode } {
  const [stage, setStage] = useState<{ scale: number; height: number; mode: StageMode }>({
    scale: 1,
    height: h,
    mode: 'stage',
  });

  useEffect(() => {
    const fit = () => {
      const forced = forcedMode();
      const { innerWidth: iw, innerHeight: ih } = window;
      const scale = Math.min(iw / w, ih / h);

      /* Two tests, and the second one is the important one.

         The stage has to be too small to read (scale under 0.62) AND the thing
         looking at it has to be something you would never present from — a
         touch device, or a window narrower than any projector. Without that
         second clause a 1024x768 4:3 projector (scale 0.53) would reflow
         itself, which is precisely the panel `--stage-h`'s 1.6x flex was built
         for. `pointer`, not `any-pointer`: a touchscreen laptop with a mouse
         plugged in reports `fine` and stays on the stage.

         Worked through: iPhone portrait 0.21 coarse -> fluid. iPhone landscape
         0.36 coarse -> fluid. iPad portrait 0.43 coarse -> fluid. iPad
         landscape 0.61 coarse -> fluid. 1024x768 projector 0.53 fine, 1024 wide
         -> STAGE. 1366x768 laptop 0.71 -> stage. 700x900 window 0.36, narrow
         -> fluid. */
      const coarse = window.matchMedia('(pointer: coarse)').matches;
      const mode: StageMode =
        forced ?? (scale < LEGIBLE_SCALE && (coarse || iw < NARROW) ? 'fluid' : 'stage');

      setStage({ scale, height: Math.min(ih / scale, h * 1.6), mode });
    };
    fit();
    window.addEventListener('resize', fit);
    /* Some mobile browsers settle their innerHeight after the rotation, not
       during the resize that precedes it. */
    window.addEventListener('orientationchange', fit);
    return () => {
      window.removeEventListener('resize', fit);
      window.removeEventListener('orientationchange', fit);
    };
  }, [w, h]);

  return stage;
}
