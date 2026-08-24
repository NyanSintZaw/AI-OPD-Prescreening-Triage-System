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
  | 'nongRiseSway'
  | 'nongExplode'
  | 'nongHeartbeat'
  | 'nongShowreel';

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
  nongExplode: { mark: 'nong', role: 'attract loop — fly apart & snap' },
  nongHeartbeat: { mark: 'nong', role: 'attract loop — heartbeat burst' },
  nongShowreel: { mark: 'nong', role: 'attract loop — random mix' },
};

/** Motions that spawn ring/petal effects around the mark and loop forever. */
export const ATTRACT_MOTIONS: MarkMotion[] = ['nongExplode', 'nongHeartbeat', 'nongShowreel'];

/** Centre of the Nong Mali viewBox (0 0 1254 1254). */
const NONG_CENTRE = 627;

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
  /**
   * Where the attract motions draw their rings and petals. Defaults to the
   * mark's parent. The effects are centred on the mark and sit behind it, so
   * the stage wants to be at least twice the mark's size; a `static` stage is
   * temporarily made `relative` and restored on cancel.
   */
  stage?: HTMLElement | null;
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
  const timers: ReturnType<typeof setTimeout>[] = [];
  const fx: HTMLElement[] = [];
  let restoreStage: (() => void) | undefined;
  let repeat: ReturnType<typeof setTimeout> | undefined;

  const track = (a: Animation) => {
    running.push(a);
    return a;
  };
  const later = (fn: () => void, ms: number) => {
    const t = setTimeout(fn, ms);
    timers.push(t);
    return t;
  };
  const handle: MotionHandle = {
    cancel: () => {
      if (repeat !== undefined) clearTimeout(repeat);
      timers.forEach(clearTimeout);
      running.forEach((a) => {
        try {
          a.cancel();
        } catch {
          /* already gone */
        }
      });
      fx.forEach((el) => el.remove());
      fx.length = 0;
      restoreStage?.();
    },
  };

  /* ── stage effects (attract motions only) ───────────────────────────────
     Rings and petals are DOM nodes drawn around the mark, not SVG parts, so
     they need a positioned host. */
  const getStage = (): HTMLElement | null => {
    const st = options.stage ?? (root.parentElement as HTMLElement | null);
    if (!st) return null;
    if (getComputedStyle(st).position === 'static') {
      const prev = st.style.position;
      st.style.position = 'relative';
      restoreStage = () => {
        st.style.position = prev;
      };
    }
    return st;
  };

  const spawn = (stage: HTMLElement, style: Partial<CSSStyleDeclaration>) => {
    const d = document.createElement('div');
    Object.assign(d.style, { position: 'absolute', pointerEvents: 'none', zIndex: '0' }, style);
    stage.appendChild(d);
    fx.push(d);
    return d;
  };

  /** A teal ring expanding out of the mark and fading. */
  const burstRing = (stage: HTMLElement, delay: number, size = 340) => {
    const r = spawn(stage, {
      left: '50%',
      top: '50%',
      width: `${size}px`,
      height: `${size}px`,
      margin: `${-size / 2}px 0 0 ${-size / 2}px`,
      border: '3px solid rgba(88,161,157,0.5)',
      borderRadius: '50%',
      opacity: '0',
    });
    const dur = 950;
    track(
      r.animate(
        [
          { transform: 'scale(0.55)', opacity: 0.75 },
          { transform: 'scale(2.1)', opacity: 0 },
        ],
        { duration: dur, delay, fill: 'forwards', easing: 'ease-out' },
      ),
    );
    later(() => r.remove(), delay + dur + 80);
  };

  /** A scatter of jasmine petals thrown outward — every third one gold. */
  const petalBurst = (
    stage: HTMLElement,
    delay: number,
    cx: string,
    cy: string,
    count: number,
    dist: number,
  ) => {
    for (let k = 0; k < count; k += 1) {
      const a = (Math.PI * 2 * k) / count + Math.random() * 0.6;
      const d = dist + Math.random() * 70;
      const petal = spawn(stage, {
        left: cx,
        top: cy,
        width: '15px',
        height: '15px',
        margin: '-8px 0 0 -8px',
        background: k % 3 === 2 ? 'rgba(216,164,88,0.85)' : 'rgba(88,161,157,0.8)',
        borderRadius: '50% 50% 50% 0',
        opacity: '0',
      });
      const dur = 1000;
      track(
        petal.animate(
          [
            { transform: 'translate(0,0) rotate(45deg) scale(0.35)', opacity: 0.95 },
            {
              transform: `translate(${Math.cos(a) * d}px,${Math.sin(a) * d}px) rotate(300deg) scale(1)`,
              opacity: 0,
            },
          ],
          { duration: dur, delay, fill: 'forwards', easing: 'cubic-bezier(.17,.67,.35,1)' },
        ),
      );
      later(() => petal.remove(), delay + dur + 80);
    }
  };

  /** Each part's angle and distance from the mark's centre, for radial motion. */
  const partGeo = () => {
    const geo: { p: SVGGeometryElement; ang: number; dist: number; i: number; bot: number }[] = [];
    [...root.querySelectorAll<SVGGeometryElement>('path,circle,ellipse')].forEach((p, i) => {
      let bb: DOMRect;
      try {
        bb = p.getBBox();
      } catch {
        return;
      }
      const dx = bb.x + bb.width / 2 - NONG_CENTRE;
      const dy = bb.y + bb.height / 2 - NONG_CENTRE;
      const st = p.style as CSSStyleDeclaration & { transformBox?: string };
      st.transformBox = 'fill-box';
      st.transformOrigin = 'center';
      geo.push({ p, ang: Math.atan2(dy, dx), dist: Math.hypot(dx, dy), i, bot: bb.y + bb.height });
    });
    return geo;
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

  if (motion === 'nongExplode' || motion === 'nongHeartbeat' || motion === 'nongShowreel') {
    /* Attract loops: built to pull eyes from across a lobby, so they are
       bigger and more theatrical than the in-app set, they throw off rings and
       petals around the mark, and they run forever without a tap.

       Each is written as a finite segment returning its own duration, so the
       showreel can chain them at random. A motion that looped internally could
       not be sequenced. */
    const stage = getStage();
    root.style.overflow = 'visible';

    /** Clear anything mid-flight and put every part back at rest. */
    const softReset = () => {
      running.splice(0).forEach((a) => {
        try {
          a.cancel();
        } catch {
          /* already gone */
        }
      });
      root.style.transform = '';
      root.querySelectorAll<SVGGeometryElement>('path,circle,ellipse').forEach((p) => {
        p.style.transform = '';
        p.style.opacity = '';
      });
    };

    /** One fly-apart-and-snap. Returns how long it occupies. */
    const explodeOnce = (): number => {
      root.style.transformOrigin = '50% 50%';
      const geo = partGeo();
      if (geo.length === 0) return 400;
      const out = 800;
      const hold = 1600;
      const back = 650;
      const n = geo.length;
      const maxBot = Math.max(...geo.map((g) => g.bot));
      geo.forEach(({ p, ang, dist, i, bot }) => {
        const d = dist * 1.2 + 160 + (i % 5) * 26;
        const tx = Math.cos(ang) * d;
        const ty = Math.sin(ang) * d;
        // the part sitting lowest is her base — it stays upright
        const spin = bot === maxBot ? 0 : (i % 2 ? 1 : -1) * (24 + ((i * 13) % 40));
        const delay = i * 16;
        track(
          p.animate(
            [
              { transform: 'translate(0,0) rotate(0deg) scale(1)' },
              { transform: `translate(${tx}px,${ty}px) rotate(${spin}deg) scale(1.05)` },
            ],
            { duration: out, delay, fill: 'forwards', easing: 'cubic-bezier(.3,1.35,.5,1)' },
          ),
        );
        track(
          p.animate(
            [
              { transform: 'translate(0,0)' },
              { transform: `translate(0,${-(12 + ((i * 7) % 16))}px)` },
              { transform: 'translate(0,0)' },
            ],
            { duration: hold, delay: out + delay, composite: 'add', easing: 'ease-in-out' },
          ),
        );
        track(
          p.animate(
            [
              { transform: `translate(${tx}px,${ty}px) rotate(${spin}deg) scale(1.05)` },
              { transform: 'translate(0,0) rotate(0deg) scale(1)' },
            ],
            {
              duration: back,
              delay: out + hold + (n - i) * 10,
              fill: 'forwards',
              easing: 'cubic-bezier(.4,0,.2,1.3)',
            },
          ),
        );
      });
      const snap = out + hold + back + n * 10;
      track(
        root.animate(
          [
            { transform: 'scale(1)' },
            { transform: 'scale(1.07)', offset: 0.4 },
            { transform: 'scale(1)' },
          ],
          { duration: 460, delay: snap - 80, easing: 'ease-out' },
        ),
      );
      if (stage) {
        burstRing(stage, snap + 60);
        petalBurst(stage, snap + 60, '50%', '50%', 9, 170);
      }
      return snap + 1400;
    };

    /** `beats` lub-dubs, each shedding rings and petals. */
    const heartbeatRun = (beats: number): number => {
      root.style.transformOrigin = '50% 50%';
      let t = 0;
      for (let k = 0; k < beats; k += 1) {
        track(
          root.animate(
            [
              { transform: 'scale(1)' },
              { transform: 'scale(1.09)', offset: 0.16 },
              { transform: 'scale(0.985)', offset: 0.34 },
              { transform: 'scale(1.16)', offset: 0.54 },
              { transform: 'scale(1)' },
            ],
            { duration: 680, delay: t, easing: 'ease-in-out' },
          ),
        );
        if (stage) {
          burstRing(stage, t + 160);
          burstRing(stage, t + 360, 300);
          petalBurst(stage, t + 240, '50%', '50%', 8, 165);
        }
        t += 1600;
      }
      return t;
    };

    /** A rise, then `turns` of sway. */
    const riseSwayRun = (turns: number): number => {
      const live = [...root.querySelectorAll<SVGGeometryElement>('path, circle, ellipse')];
      if (live.length === 0) return 400;
      const ln = live.length;
      live.forEach((p, i) => {
        const st = p.style as CSSStyleDeclaration & { transformBox?: string };
        st.transformBox = 'fill-box';
        st.transformOrigin = 'center';
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
          iterations: turns,
          easing: 'ease-in-out',
        }),
      );
      return RISE_TOTAL + SWAY_DUR * turns;
    };

    if (motion === 'nongHeartbeat') {
      root.style.transformOrigin = '50% 50%';
      track(
        root.animate(
          [
            { transform: 'scale(0)', opacity: 0 },
            { transform: 'scale(1.07)', opacity: 1, offset: 0.7 },
            { transform: 'scale(1)', opacity: 1 },
          ],
          { duration: 550, fill: 'backwards', easing: SPRING },
        ),
      );
      const beat = () => {
        softReset();
        heartbeatRun(1);
        later(beat, 1600);
      };
      later(beat, 700);
      return handle;
    }

    if (motion === 'nongExplode') {
      track(
        root.animate(
          [
            { transform: 'scale(0.7)', opacity: 0 },
            { transform: 'scale(1)', opacity: 1 },
          ],
          { duration: 600, fill: 'backwards', easing: GLIDE },
        ),
      );
      const cycle = () => {
        softReset();
        later(cycle, explodeOnce() + 100);
      };
      later(cycle, 900);
      return handle;
    }

    /* nongShowreel — explode, heartbeat and sway in a random order, with the
       repeat counts varied too, so a passer-by does not see a fixed loop. The
       same act never runs twice in a row. */
    const randInt = (lo: number, hi: number) => lo + Math.floor(Math.random() * (hi - lo + 1));
    let last = '';
    const step = () => {
      softReset();
      const acts = ['explode', 'heartbeat', 'sway'].filter((a) => a !== last);
      const pick = acts[Math.floor(Math.random() * acts.length)];
      last = pick;
      let dur: number;
      if (pick === 'explode') dur = explodeOnce();
      else if (pick === 'heartbeat') dur = heartbeatRun(randInt(2, 3));
      else dur = riseSwayRun(randInt(2, 3));
      later(step, dur + 250);
    };
    later(step, 300);
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
