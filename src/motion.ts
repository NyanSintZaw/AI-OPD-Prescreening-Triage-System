/**
 * MALI logo motion — the seven approved animations for the two brand marks,
 * ported from the Brand Guidelines canvas.
 *
 * These are Web Animations API sequences over the SVG's own paths, not CSS
 * keyframes: they measure each path with `getTotalLength()` to draw it, wipe
 * shapes with `clip-path`, and stagger per-path with a spring curve. That is
 * why they live here rather than in `components.css`.
 *
 *   playMark(el, 'nongBloom')
 *
 * `el` is any element containing the mark's `<svg>` (the element the component
 * renders is fine). Every call resets the mark first, so replaying mid-flight
 * is safe. Returns a handle with `cancel()`.
 *
 * Respects `prefers-reduced-motion`: the mark snaps to its resting state and no
 * animation is scheduled, unless you pass `{ force: true }`.
 */

export type MarkMotion =
  | 'budDraw'
  | 'budFilled'
  | 'budHand'
  | 'budGrow'
  | 'nongRise'
  | 'nongWave'
  | 'nongBloom'
  | 'nongRiseSway';

/** Which mark each motion belongs to — `Mark` (bud) or `NongMali`. */
export const MARK_MOTIONS: Record<MarkMotion, { mark: 'bud' | 'nong'; role: string }> = {
  budDraw: { mark: 'bud', role: 'loading' },
  budFilled: { mark: 'bud', role: 'reveal' },
  budHand: { mark: 'bud', role: 'signature sketch' },
  budGrow: { mark: 'bud', role: 'step complete' },
  nongRise: { mark: 'nong', role: 'quiet entrance' },
  nongWave: { mark: 'nong', role: 'greeting' },
  nongBloom: { mark: 'nong', role: 'welcome' },
  nongRiseSway: { mark: 'nong', role: 'idle loop' },
};

/* nongRiseSway timing. The rise finishes once its last-staggered part lands;
   the sway then runs whole cycles before she rises again. */
const RISE_DUR = 600;
const RISE_STAGGER = 500;
const RISE_TOTAL = RISE_DUR + RISE_STAGGER;
const SWAY_DUR = 3600;
/* Turns of sway before she rises again. */
const SWAY_CYCLES = 3;
const RISE_SWAY_PERIOD = RISE_TOTAL + SWAY_DUR * SWAY_CYCLES;

export interface PlayOptions {
  /** Run even when the viewer prefers reduced motion. Default false. */
  force?: boolean;
}

export interface MotionHandle {
  cancel: () => void;
}

/** nongBloom's settle — a whisper, because it runs under a welcome headline. */
const SETTLE_KEYFRAMES: Keyframe[] = [
  { transform: 'rotate(0deg) translateY(0)' },
  { transform: 'rotate(1.6deg) translateY(-3px)' },
  { transform: 'rotate(0deg) translateY(0)' },
  { transform: 'rotate(-1.6deg) translateY(-3px)' },
  { transform: 'rotate(0deg) translateY(0)' },
];

/* nongRiseSway's sway. Read from across a lobby rather than at arm's length,
   so it carries roughly 2.5x the rotation, 3x the lift, and a slight breath in
   scale — the settle amplitude above is invisible at that distance. The tilt
   pivots low, the way a flower moves on its stem. */
const SWAY_KEYFRAMES: Keyframe[] = [
  { transform: 'rotate(0deg) translateY(0) scale(1)' },
  { transform: 'rotate(4deg) translateY(-9px) scale(1.02)', offset: 0.25 },
  { transform: 'rotate(0deg) translateY(-2px) scale(1)', offset: 0.5 },
  { transform: 'rotate(-4deg) translateY(-9px) scale(1.02)', offset: 0.75 },
  { transform: 'rotate(0deg) translateY(0) scale(1)' },
];

const SPRING = 'cubic-bezier(.34,1.56,.64,1)';
const GLIDE = 'cubic-bezier(.22,1,.36,1)';

interface SvgElWithSplit extends SVGSVGElement {
  _splitG?: SVGGElement | null;
  _silEl?: SVGPathElement | null;
}

function prefersReduced(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

/** Clear any in-flight animation and restore the mark to its authored state. */
function reset(host: Element): SvgElWithSplit | null {
  const root = (host instanceof SVGSVGElement ? host : host.querySelector('svg')) as
    | SvgElWithSplit
    | null;
  if (!root) return null;

  if (root._splitG) {
    root._splitG.remove();
    root._splitG = null;
    if (root._silEl) root._silEl.style.display = '';
  }
  root.style.transform = '';
  root.querySelectorAll<SVGGeometryElement>('path, circle, ellipse').forEach((p) => {
    const s = p.style as CSSStyleDeclaration & { transformBox?: string };
    s.strokeDasharray = '';
    s.strokeDashoffset = '';
    s.fillOpacity = '';
    s.stroke = '';
    s.strokeWidth = '';
    s.clipPath = '';
    s.opacity = '';
    s.transform = '';
    s.display = '';
    s.transformBox = '';
    s.transformOrigin = '';
  });
  root.getAnimations({ subtree: true }).forEach((a) => a.cancel());
  return root;
}

function lengthOf(p: SVGGeometryElement): number {
  try {
    return p.getTotalLength();
  } catch {
    return 0;
  }
}

/** Play one of the seven approved mark motions. */
export function playMark(
  host: Element | null | undefined,
  motion: MarkMotion,
  options: PlayOptions = {},
): MotionHandle {
  const noop: MotionHandle = { cancel: () => {} };
  if (!host) return noop;

  const root = reset(host);
  if (!root) return noop;
  if (prefersReduced() && !options.force) return noop;

  const running: Animation[] = [];
  let repeat: ReturnType<typeof setTimeout> | undefined;
  const track = (a: Animation) => {
    running.push(a);
    return a;
  };
  const handle: MotionHandle = {
    cancel: () => {
      if (repeat !== undefined) clearTimeout(repeat);
      running.forEach((a) => a.cancel());
    },
  };

  const allParts = [...root.querySelectorAll<SVGGeometryElement>('path, circle')];
  let t = 0;

  if (motion === 'budDraw') {
    // Each outline draws itself, then its fill arrives; the stamen dots pop.
    root.querySelectorAll<SVGPathElement>('path').forEach((p) => {
      const inStroke = p.closest('g[stroke]') || p.getAttribute('stroke');
      const len = lengthOf(p);
      if (!len) return;
      const dur = Math.max(250, Math.min(900, len * 0.55));
      p.style.strokeDasharray = String(len);
      p.style.strokeDashoffset = String(len);
      if (!inStroke) {
        p.style.stroke = p.getAttribute('fill') ?? '';
        p.style.strokeWidth = '2.5';
        p.style.fillOpacity = '0';
        track(
          p.animate([{ strokeDashoffset: len }, { strokeDashoffset: 0 }], {
            duration: dur,
            delay: t,
            fill: 'forwards',
            easing: 'ease-in-out',
          }),
        );
        track(
          p.animate([{ fillOpacity: 0 }, { fillOpacity: 1 }], {
            duration: 350,
            delay: t + dur * 0.7,
            fill: 'forwards',
          }),
        );
      } else {
        track(
          p.animate([{ strokeDashoffset: len }, { strokeDashoffset: 0 }], {
            duration: dur,
            delay: t,
            fill: 'forwards',
            easing: 'ease-out',
          }),
        );
      }
      t += dur * 0.55;
    });
    root.querySelectorAll<SVGCircleElement>('circle').forEach((c, i) => {
      const s = c.style as CSSStyleDeclaration & { transformBox?: string };
      s.transformBox = 'fill-box';
      s.transformOrigin = 'center';
      track(
        c.animate([{ transform: 'scale(0)' }, { transform: 'scale(1.4)' }, { transform: 'scale(1)' }], {
          duration: 400,
          delay: t + i * 120,
          fill: 'backwards',
          easing: SPRING,
        }),
      );
    });
    return handle;
  }

  if (motion === 'budFilled') {
    // Each shape wipes upward in turn.
    allParts.forEach((p) => {
      track(
        p.animate([{ clipPath: 'inset(100% 0 0 0)' }, { clipPath: 'inset(0 0 0 0)' }], {
          duration: 480,
          delay: t,
          fill: 'backwards',
          easing: 'ease-out',
        }),
      );
      t += 216;
    });
    return handle;
  }

  if (motion === 'budHand') {
    // Signature sketch: the silhouette is split into its sub-paths, regrouped
    // by bounding box, and each petal wipes in from a different direction —
    // outer leaves up, the centre across, then the stamens draw and dot.
    const sil = allParts.find(
      (p) =>
        p.tagName === 'path' &&
        !p.closest('g[stroke]') &&
        (p.getAttribute('fill') ?? '').toUpperCase() !== '#DDE8DF',
    ) as SVGPathElement | undefined;
    const facet = allParts.find((p) => (p.getAttribute('fill') ?? '').toUpperCase() === '#DDE8DF');
    const stamenPaths = [...root.querySelectorAll<SVGPathElement>('g[stroke] path')];
    const dots = [...root.querySelectorAll<SVGCircleElement>('circle')];
    if (!sil) return handle;

    const fillCol = sil.getAttribute('fill') ?? '';
    const loops = (sil.getAttribute('d') ?? '').match(/M[^M]+/g) ?? [];
    const ns = 'http://www.w3.org/2000/svg';
    const g = document.createElementNS(ns, 'g');
    root.appendChild(g);

    type Loop = { d: string; b: DOMRect; kids?: Loop[] };
    const info: Loop[] = loops.map((dd) => {
      const tp = document.createElementNS(ns, 'path');
      tp.setAttribute('d', dd);
      g.appendChild(tp);
      const b = tp.getBBox();
      tp.remove();
      return { d: dd, b };
    });
    const area = (o: Loop) => o.b.width * o.b.height;
    const inside = (a: Loop, b: Loop) =>
      a.b.x >= b.b.x - 1 &&
      a.b.y >= b.b.y - 1 &&
      a.b.x + a.b.width <= b.b.x + b.b.width + 1 &&
      a.b.y + a.b.height <= b.b.y + b.b.height + 1 &&
      area(a) < area(b);

    const roots: Loop[] = [];
    info.forEach((o) => {
      let host2: Loop | null = null;
      info.forEach((p2) => {
        if (p2 !== o && inside(o, p2) && (!host2 || area(p2) < area(host2))) host2 = p2;
      });
      if (host2) ((host2 as Loop).kids ??= []).push(o);
      else roots.push(o);
    });

    const shapes = roots.map((r) => {
      const el = document.createElementNS(ns, 'path');
      el.setAttribute('d', r.d + (r.kids ?? []).map((k) => k.d).join(' '));
      el.setAttribute('fill', fillCol);
      el.setAttribute('fill-rule', 'evenodd');
      g.appendChild(el);
      return { el, b: r.b };
    });

    let mid = shapes[0];
    shapes.forEach((s) => {
      if (s.b.width * s.b.height > mid.b.width * mid.b.height) mid = s;
    });
    const midCx = mid.b.x + mid.b.width / 2;
    const lefts = shapes
      .filter((s) => s !== mid && s.b.x + s.b.width / 2 < midCx)
      .sort((a, b) => a.b.x - b.b.x);
    const rights = shapes
      .filter((s) => s !== mid && s.b.x + s.b.width / 2 >= midCx)
      .sort((a, b) => a.b.x - b.b.x);

    sil.style.display = 'none';
    root._silEl = sil;
    root._splitG = g;

    const seq = [
      ...lefts.map((s) => ({ el: s.el, from: 'inset(100% 0 0 0)' })),
      { el: mid.el, from: 'inset(0 100% 0 0)' },
      ...rights.map((s) => ({ el: s.el, from: 'inset(0 0 100% 0)' })),
    ];
    seq.forEach(({ el, from }) => {
      track(
        el.animate([{ clipPath: from }, { clipPath: 'inset(0 0 0 0)' }], {
          duration: 560,
          delay: t,
          fill: 'backwards',
          easing: 'ease-in-out',
        }),
      );
      t += 420;
    });
    if (facet) {
      track(
        facet.animate([{ opacity: 0 }, { opacity: 1 }], {
          duration: 450,
          delay: t,
          fill: 'backwards',
          easing: 'ease-out',
        }),
      );
      t += 500;
    }
    stamenPaths.forEach((p, i) => {
      const len = lengthOf(p);
      if (!len) return;
      p.style.strokeDasharray = String(len);
      p.style.strokeDashoffset = String(len);
      track(
        p.animate([{ strokeDashoffset: len }, { strokeDashoffset: 0 }], {
          duration: 320,
          delay: t,
          fill: 'forwards',
          easing: 'ease-out',
        }),
      );
      const dot = dots[i];
      if (dot) {
        const s = dot.style as CSSStyleDeclaration & { transformBox?: string };
        s.transformBox = 'fill-box';
        s.transformOrigin = 'center';
        track(
          dot.animate(
            [{ transform: 'scale(0)' }, { transform: 'scale(1.4)' }, { transform: 'scale(1)' }],
            { duration: 300, delay: t + 260, fill: 'backwards', easing: SPRING },
          ),
        );
      }
      t += 380;
    });
    return handle;
  }

  if (motion === 'budGrow') {
    // Grows from its base, part by part, with a small overshoot.
    allParts.forEach((p) => {
      const s = p.style as CSSStyleDeclaration & { transformBox?: string };
      s.transformBox = 'fill-box';
      s.transformOrigin = 'center bottom';
      track(
        p.animate(
          [
            { transform: 'scale(0.2)', opacity: 0 },
            { transform: 'scale(1.06)', opacity: 1, offset: 0.75 },
            { transform: 'scale(1)', opacity: 1 },
          ],
          { duration: 480, delay: t, fill: 'backwards', easing: SPRING },
        ),
      );
      t += 130;
    });
    return handle;
  }

  const parts = [...root.querySelectorAll<SVGGeometryElement>('path, circle, ellipse')];
  const n = Math.max(parts.length, 1);

  if (motion === 'nongRise') {
    parts.forEach((p, i) => {
      const s = p.style as CSSStyleDeclaration & { transformBox?: string };
      s.transformBox = 'fill-box';
      s.transformOrigin = 'center';
      track(
        p.animate(
          [
            { transform: 'translateY(14px)', opacity: 0 },
            { transform: 'translateY(0)', opacity: 1 },
          ],
          { duration: 600, delay: i * (500 / n), fill: 'backwards', easing: GLIDE },
        ),
      );
    });
    return handle;
  }

  if (motion === 'nongWave') {
    root.style.transformOrigin = '50% 100%';
    track(
      root.animate(
        [
          { transform: 'scale(0)', opacity: 0 },
          { transform: 'scale(1.06)', opacity: 1, offset: 0.6 },
          { transform: 'scale(1)', opacity: 1 },
        ],
        { duration: 600, fill: 'backwards', easing: SPRING },
      ),
    );
    track(
      root.animate(
        [
          { transform: 'rotate(0deg)' },
          { transform: 'rotate(-6deg)' },
          { transform: 'rotate(5deg)' },
          { transform: 'rotate(-3deg)' },
          { transform: 'rotate(0deg)' },
        ],
        { duration: 900, delay: 650, easing: 'ease-in-out' },
      ),
    );
    return handle;
  }

  if (motion === 'nongRiseSway') {
    // Idle loop: she glides up, sways for a few seconds, then rises again.
    // Scheduled rather than one infinite keyframe set, because the rise has to
    // re-run each cycle — an `iterations: Infinity` sway alone only ever sways.
    const cycle = () => {
      running.splice(0).forEach((a) => a.cancel());
      /* Re-query every cycle rather than reusing the list captured on the first
         pass. A host that re-renders can replace the SVG's children (React
         re-applies dangerouslySetInnerHTML), leaving the captured nodes
         detached — the sway survives because it targets the <svg> itself, but
         the rise would animate nodes no longer in the document. */
      const live = [...root.querySelectorAll<SVGGeometryElement>('path, circle, ellipse')];
      if (live.length === 0) {
        /* Nothing to rise yet — the host has not written the mark's paths.
           Try again next frame instead of burning the cycle on an empty set. */
        requestAnimationFrame(cycle);
        return;
      }
      const ln = live.length;
      live.forEach((p, i) => {
        const s2 = p.style as CSSStyleDeclaration & { transformBox?: string };
        s2.transformBox = 'fill-box';
        s2.transformOrigin = 'center';
        track(
          p.animate(
            [
              { transform: 'translateY(14px)', opacity: 0 },
              { transform: 'translateY(0)', opacity: 1 },
            ],
            { duration: RISE_DUR, delay: i * (RISE_STAGGER / ln), fill: 'backwards', easing: GLIDE },
          ),
        );
      });
      root.style.transformOrigin = '50% 85%';
      track(
        root.animate(SWAY_KEYFRAMES, {
          duration: SWAY_DUR,
          delay: RISE_TOTAL,
          iterations: SWAY_CYCLES,
          easing: 'ease-in-out',
        }),
      );
      repeat = setTimeout(cycle, RISE_SWAY_PERIOD);
    };
    cycle();
    return handle;
  }

  // nongBloom — every part springs open in turn, then she settles into a slow
  // sway. The sway loops, so it is the one motion that keeps running.
  parts.forEach((p, i) => {
    const s = p.style as CSSStyleDeclaration & { transformBox?: string };
    s.transformBox = 'fill-box';
    s.transformOrigin = 'center';
    track(
      p.animate(
        [
          { transform: 'scale(0.3)', opacity: 0 },
          { transform: 'scale(1.08)', opacity: 1, offset: 0.7 },
          { transform: 'scale(1)', opacity: 1 },
        ],
        { duration: 520, delay: i * (700 / n), fill: 'backwards', easing: SPRING },
      ),
    );
  });
  track(
    root.animate(SETTLE_KEYFRAMES, {
      duration: 4200,
      delay: 1220,
      iterations: Infinity,
      easing: 'ease-in-out',
    }),
  );
  return handle;
}
