import { useEffect, useRef, useState } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import type { VoiceCallState } from '../../hooks/useVoiceCall';

type AvatarPose = 'idle' | 'listening' | 'thinking' | 'speaking';

interface NurseAvatarProps {
  state: VoiceCallState | 'idle';
  /** Live loudness of the assistant's voice (0..1) — drives the mouth
   *  while speaking. Polled from a rAF loop, so it must be identity-stable
   *  (useVoiceCall.getOutputLevel). */
  getLevel?: () => number;
}

function toPose(state: VoiceCallState | 'idle'): AvatarPose {
  switch (state) {
    case 'listening':
      return 'listening';
    case 'speaking':
      return 'speaking';
    case 'thinking':
    case 'uploading':
    case 'starting':
    case 'greeting':
      return 'thinking';
    default:
      return 'idle';
  }
}

// Palette on top of the kiosk design tokens. Skin/hair/paper are fixed;
// uniform + accents follow the brand vars so a token retheme re-dresses
// the nurse automatically. Shading uses gradients built from these same
// base colors (see <defs>) rather than one-off hardcoded tones.
const SKIN = '#f6cfae';
const SKIN_LIGHT = '#fce3c8';
const SKIN_SHADE = '#e5b590';
const HAIR = '#4a3628';
const HAIR_LIGHT = '#6e5642';
const HAIR_DEEP = '#33241a';
const IRIS = '#6b4a35';
const IRIS_LIGHT = '#8a6446';
const IRIS_DEEP = '#3c2718';
const BLUSH = '#f2a396';
const MOUTH_STROKE = '#b96b5e';
const MOUTH_FILL = '#8a4b44';
const BOARD = '#c8965f';
const BOARD_EDGE = '#a97b4b';
const PAPER = '#fffdf8';
const RULE = '#e3e7f2';
const INK = '#5a6ba8';
const PRIMARY = 'var(--k-primary, #3f4e87)';
const PRIMARY_DEEP = 'var(--k-primary-deep, #2d3963)';
const TINT_BORDER = 'var(--k-primary-tint-border, #b9c3e6)';

const springy = { type: 'spring' as const, stiffness: 130, damping: 17 };
const laggy = { type: 'spring' as const, stiffness: 90, damping: 11, delay: 0.04 };
const staggered = { ...springy, delay: 0.08 };

// Per-pose transforms. The head pivots at the neck; the clipboard is
// drawn in its raised "writing" position and lowered for the other
// poses; the pen hand rides from the paper up to the chin for thinking.
const HEAD_POSES: Record<AvatarPose, { rotate: number; y: number }> = {
  idle: { rotate: 0, y: 0 },
  listening: { rotate: 7, y: 5 },
  thinking: { rotate: -5, y: 0 },
  speaking: { rotate: 0, y: 0 },
};

const PUPIL_POSES: Record<AvatarPose, { x: number; y: number }> = {
  idle: { x: 0, y: 0 },
  listening: { x: 3, y: 4.5 },
  thinking: { x: -3.5, y: -4 },
  speaking: { x: 0, y: 0 },
};

const EYEBROW_POSES: Record<AvatarPose, { y: number; tilt: number }> = {
  idle: { y: 0, tilt: 0 },
  listening: { y: 0, tilt: 0 },
  thinking: { y: 2.5, tilt: 5 }, // knit inward/down while concentrating
  speaking: { y: -2, tilt: -2 }, // slight raise while talking
};

// Board tilts toward the writing hand (top edge leans viewer-right) —
// the natural angle for a right-handed writer cradling it in her left arm.
const PAD_POSES: Record<AvatarPose, { y: number; rotate: number; scale: number }> = {
  listening: { y: 0, rotate: 6, scale: 1 },
  idle: { y: 58, rotate: 8, scale: 0.97 },
  speaking: { y: 58, rotate: 8, scale: 0.97 },
  thinking: { y: 62, rotate: 9, scale: 0.95 },
};

const HAND_POSES: Record<AvatarPose, { x: number; y: number; rotate: number }> = {
  listening: { x: 0, y: 0, rotate: 0 },
  idle: { x: 14, y: 74, rotate: 8 },
  speaking: { x: 14, y: 74, rotate: 8 },
  thinking: { x: 30, y: -88, rotate: -24 },
};

// ── Mouth: 4 visemes sharing one path template ───────────────────────────
// [halfWidth, topOffset, bottomOffset] around a fixed centerline — every
// shape uses the exact same two-quadratic-curve command structure, so the
// numbers (not the path) are what get interpolated per rAF frame.
type Viseme = readonly [halfWidth: number, top: number, bottom: number];
const MOUTH_VISEMES: Record<'closed' | 'small' | 'mid' | 'open', Viseme> = {
  closed: [11, -0.5, 8.5],
  small: [9.5, -3, 6.5],
  mid: [8.5, -6, 10.5],
  open: [7.5, -9.5, 14.5],
};
const MOUTH_ORDER = ['closed', 'small', 'mid', 'open'] as const;
const MOUTH_CX = 150;
const MOUTH_CY = 190.5;

function buildMouthPath([hw, top, bottom]: Viseme, cx = MOUTH_CX, cy = MOUTH_CY): string {
  const yTop = (cy + top).toFixed(2);
  const yBot = (cy + bottom).toFixed(2);
  const xL = (cx - hw).toFixed(2);
  const xR = (cx + hw).toFixed(2);
  return `M${xL},${cy} Q${cx},${yTop} ${xR},${cy} Q${cx},${yBot} ${xL},${cy} Z`;
}

function lerpViseme(a: Viseme, b: Viseme, t: number): Viseme {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

/** One eye: iris gradient, dual catchlights, lash line, spring-tracked
 *  pupil target (pose target + saccade jitter), eased blink via scaleY. */
function NurseEye({
  cx,
  target,
  blink,
}: {
  cx: number;
  target: { x: number; y: number };
  blink: boolean;
}) {
  return (
    <motion.g animate={target} transition={springy}>
      <motion.g
        style={{ transformBox: 'fill-box', transformOrigin: 'center' }}
        animate={{ scaleY: blink ? 0.12 : 1 }}
        transition={{ duration: 0.1, ease: 'easeInOut' }}
      >
        <circle cx={cx} cy={158} r={6.4} fill="url(#nv-iris-grad)" />
        <circle cx={cx} cy={158} r={2.7} fill="#241a14" />
        <circle cx={cx - 1.6} cy={155.6} r={1.5} fill="#ffffff" />
        <circle cx={cx + 2.2} cy={160.2} r={0.8} fill="#ffffff" opacity={0.85} />
        {/* Soft upper lid line (no lash flick — it read as clumped lashes) */}
        <path
          d={`M${cx - 6},153.2 Q${cx},150.4 ${cx + 6},153.2`}
          stroke="#3b2f28"
          strokeWidth={1.1}
          strokeLinecap="round"
          fill="none"
          opacity={0.85}
        />
      </motion.g>
    </motion.g>
  );
}

/**
 * The kiosk's 2D nurse — a layered SVG character synced to the voice
 * pipeline. While the patient talks she looks down at her clipboard and
 * writes; while the engine processes she pauses pen-to-chin; while the
 * assistant speaks she looks up and her mouth follows the live TTS
 * loudness (amplitude lip sync via getLevel). Purely decorative — the
 * status chip next to the stage carries the accessible state.
 */
export function NurseAvatar({ state, getLevel }: NurseAvatarProps) {
  const reduce = useReducedMotion();
  const pose = toPose(state);
  const speaking = pose === 'speaking' && !reduce;
  const listening = pose === 'listening' && !reduce;

  // Randomized blink — a quick eyelid close every ~3-6 s, occasionally a
  // fast double-blink, with a slightly varied close duration each time.
  const [blink, setBlink] = useState(false);
  useEffect(() => {
    if (reduce) return;
    const timers: number[] = [];
    const schedule = () => {
      const t1 = window.setTimeout(() => {
        const closeDur = 90 + Math.random() * 70;
        const doDouble = Math.random() < 0.18;
        setBlink(true);
        const t2 = window.setTimeout(() => {
          setBlink(false);
          if (doDouble) {
            const t3 = window.setTimeout(() => {
              setBlink(true);
              const t4 = window.setTimeout(() => {
                setBlink(false);
                schedule();
              }, closeDur);
              timers.push(t4);
            }, 110);
            timers.push(t3);
          } else {
            schedule();
          }
        }, closeDur);
        timers.push(t2);
      }, 2800 + Math.random() * 3200);
      timers.push(t1);
    };
    schedule();
    return () => timers.forEach((id) => window.clearTimeout(id));
  }, [reduce]);

  // Eye saccades — a small randomized offset re-rolled every 1-4 s, biased
  // by pose (down while writing, up while thinking, centered otherwise).
  const [jitter, setJitter] = useState({ x: 0, y: 0 });
  useEffect(() => {
    if (reduce) {
      setJitter({ x: 0, y: 0 });
      return;
    }
    let timer = 0;
    const schedule = () => {
      timer = window.setTimeout(() => {
        setJitter({ x: (Math.random() * 2 - 1) * 1.6, y: (Math.random() * 2 - 1) * 1.6 });
        schedule();
      }, 1000 + Math.random() * 3000);
    };
    schedule();
    return () => window.clearTimeout(timer);
  }, [reduce, pose]);

  // Amplitude lip sync: poll the playback analyser at frame rate, smooth
  // it (fast attack / slower decay so the mouth snaps open on syllables
  // but doesn't chatter shut between them), then glide the mouth outline
  // across the 4 viseme shapes — written straight to the SVG node, no
  // React state at 60 fps.
  const mouthRef = useRef<SVGPathElement | null>(null);
  useEffect(() => {
    if (!speaking || !getLevel) return;
    let raf = 0;
    let smoothed = 0;
    const tick = () => {
      const target = getLevel();
      smoothed += (target - smoothed) * (target > smoothed ? 0.5 : 0.22);
      const idx = Math.min(smoothed, 1) * (MOUTH_ORDER.length - 1);
      const i0 = Math.floor(idx);
      const i1 = Math.min(i0 + 1, MOUTH_ORDER.length - 1);
      const frac = idx - i0;
      const shape = lerpViseme(MOUTH_VISEMES[MOUTH_ORDER[i0]], MOUTH_VISEMES[MOUTH_ORDER[i1]], frac);
      const el = mouthRef.current;
      if (el) el.setAttribute('d', buildMouthPath(shape));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [speaking, getLevel]);

  const headPose = HEAD_POSES[pose];
  const brow = EYEBROW_POSES[pose];
  const staticVisemeKey = reduce ? 'closed' : pose === 'thinking' ? 'small' : 'closed';
  const eyeTarget = {
    x: PUPIL_POSES[pose].x + (reduce ? 0 : jitter.x),
    y: PUPIL_POSES[pose].y + (reduce ? 0 : jitter.y),
  };

  return (
    <svg
      viewBox="0 0 300 400"
      role="img"
      aria-label={`assistant ${state}`}
      style={{ display: 'block' }}
    >
      <defs>
        <radialGradient id="nv-skin-grad" cx="42%" cy="30%" r="75%">
          <stop offset="0%" stopColor={SKIN_LIGHT} />
          <stop offset="55%" stopColor={SKIN} />
          <stop offset="100%" stopColor={SKIN_SHADE} />
        </radialGradient>
        <linearGradient id="nv-hair-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={HAIR_LIGHT} />
          <stop offset="45%" stopColor={HAIR} />
          <stop offset="100%" stopColor={HAIR_DEEP} />
        </linearGradient>
        <linearGradient id="nv-uniform-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={PRIMARY} />
          <stop offset="100%" stopColor={PRIMARY_DEEP} />
        </linearGradient>
        <radialGradient id="nv-iris-grad" cx="38%" cy="32%" r="70%">
          <stop offset="0%" stopColor={IRIS_LIGHT} />
          <stop offset="60%" stopColor={IRIS} />
          <stop offset="100%" stopColor={IRIS_DEEP} />
        </radialGradient>
        <radialGradient id="nv-blush-grad" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={BLUSH} stopOpacity={0.75} />
          <stop offset="100%" stopColor={BLUSH} stopOpacity={0} />
        </radialGradient>
        <radialGradient id="nv-vignette" cx="50%" cy="36%" r="65%">
          <stop offset="55%" stopColor="#1b2340" stopOpacity={0} />
          <stop offset="100%" stopColor="#1b2340" stopOpacity={0.16} />
        </radialGradient>
        <filter id="nv-shadow-blur" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="6" />
        </filter>
      </defs>

      {/* Soft vignette behind the figure — static, does not breathe. */}
      <ellipse cx="150" cy="178" rx="150" ry="192" fill="url(#nv-vignette)" />
      {/* Elliptical contact shadow — mostly hidden under the torso, peeks
          out at the edges so she sits in the tile. */}
      <ellipse
        cx="150"
        cy="397"
        rx="98"
        ry="12"
        fill="#1b2340"
        opacity="0.2"
        filter="url(#nv-shadow-blur)"
      />

      {/* Whole figure breathes gently (chest lift + a hair of vertical bob). */}
      <motion.g
        style={{ transformBox: 'fill-box', transformOrigin: '50% 100%' }}
        animate={reduce ? undefined : { scale: [1, 1.012, 1], y: [0, -1.5, 0] }}
        transition={{ duration: 3.2, repeat: Infinity, ease: 'easeInOut' }}
      >
        {/* ── Torso / scrubs ─────────────────────────────────────────── */}
        <path
          d="M60,400 V322 Q60,258 118,241 L150,232 L182,241 Q240,258 240,322 V400 Z"
          fill="url(#nv-uniform-grad)"
        />
        {/* Diagonal sheen + underarm fold shadows */}
        <path
          d="M78,268 Q100,250 128,246 L118,290 Q92,300 74,318 Z"
          fill="#ffffff"
          opacity="0.09"
        />
        <path
          d="M76,300 Q92,290 104,296 Q90,312 80,336 Z"
          fill={PRIMARY_DEEP}
          opacity="0.18"
        />
        <path
          d="M224,300 Q208,290 196,296 Q210,312 220,336 Z"
          fill={PRIMARY_DEEP}
          opacity="0.18"
        />
        <path d="M132,238 L150,264 L168,238 L150,246 Z" fill={PRIMARY_DEEP} />
        {/* Collar fold lines */}
        <path d="M136,240 Q142,250 148,247" stroke={PRIMARY_DEEP} strokeWidth="1.6" strokeLinecap="round" fill="none" opacity="0.5" />
        <path d="M164,240 Q158,250 152,247" stroke={PRIMARY_DEEP} strokeWidth="1.6" strokeLinecap="round" fill="none" opacity="0.5" />
        {/* Front buttons */}
        <circle cx="150" cy="258" r="2.2" fill={PRIMARY_DEEP} opacity="0.6" />
        <circle cx="150" cy="274" r="2.2" fill={PRIMARY_DEEP} opacity="0.6" />
        {/* ID badge */}
        <g transform="translate(103,288) rotate(-6)">
          <rect width="30" height="21" rx="4" fill="#ffffff" stroke={TINT_BORDER} />
          <rect x="4" y="4" width="9" height="13" rx="2" fill={SKIN} />
          <rect x="16" y="6" width="10" height="3" rx="1.5" fill={TINT_BORDER} />
          <rect x="16" y="12" width="8" height="3" rx="1.5" fill={RULE} />
        </g>
        {/* Chest pocket with a tiny medical cross + pen peeking out */}
        <g transform="translate(186,296)">
          <rect width="28" height="22" rx="4" fill={PRIMARY_DEEP} opacity="0.55" />
          <rect x="11.5" y="5" width="5" height="13" rx="1.5" fill="#ffffff" opacity="0.9" />
          <rect x="7.5" y="9" width="13" height="5" rx="1.5" fill="#ffffff" opacity="0.9" />
          <rect x="20" y="-9" width="4" height="14" rx="2" fill={PRIMARY_DEEP} transform="rotate(10,22,-2)" />
        </g>

        {/* Neck — wide with a slight flare into the shoulders so the head
            doesn't read as perched on a stick. */}
        <path d="M133,204 h34 v14 q0,10 9,14 h-52 q9,-4 9,-14 Z" fill={SKIN_SHADE} />

        {/* ── Head (pivots at the neck) ──────────────────────────────── */}
        <motion.g
          style={{ transformBox: 'fill-box', transformOrigin: '50% 92%' }}
          animate={
            listening
              ? {
                  // Tilted toward the clipboard, with an affirming nod
                  // every few seconds while the patient talks.
                  rotate: [headPose.rotate, headPose.rotate + 3.5, headPose.rotate],
                  y: [headPose.y, headPose.y + 2, headPose.y],
                }
              : { rotate: headPose.rotate, y: headPose.y }
          }
          transition={
            listening ? { duration: 0.7, repeat: Infinity, repeatDelay: 3 } : springy
          }
        >
          {/* Hair-back (behind the face) and bangs+cap (in front of the
              face) ride the same lagged spring for follow-through — two
              groups sharing one animation so they move in lockstep even
              though the face has to be painted between them. */}
          {reduce ? (
            <g>
              <circle cx="150" cy="148" r="72" fill="url(#nv-hair-grad)" />
              <path d="M84,150 q-6,52 12,74 l14,-8 q-12,-28 -8,-62 Z" fill={HAIR} />
              <path d="M216,150 q6,52 -12,74 l-14,-8 q12,-28 8,-62 Z" fill={HAIR} />
            </g>
          ) : (
            <motion.g
              key={`hairback-${pose}`}
              style={{ transformBox: 'fill-box', transformOrigin: '50% 88%' }}
              initial={{ rotate: 4 }}
              animate={{ rotate: 0 }}
              transition={laggy}
            >
              {/* Hair behind the face */}
              <circle cx="150" cy="148" r="72" fill="url(#nv-hair-grad)" />
              <path d="M84,150 q-6,52 12,74 l14,-8 q-12,-28 -8,-62 Z" fill={HAIR} />
              <path d="M216,150 q6,52 -12,74 l-14,-8 q12,-28 8,-62 Z" fill={HAIR} />
            </motion.g>
          )}

          {/* Ears */}
          <circle cx="93" cy="160" r="9" fill={SKIN_SHADE} />
          <circle cx="207" cy="160" r="9" fill={SKIN_SHADE} />
          {/* Face */}
          <circle cx="150" cy="158" r="58" fill="url(#nv-skin-grad)" />
          {/* Forehead highlight + jaw shadow */}
          <ellipse cx="132" cy="118" rx="20" ry="12" fill="#ffffff" opacity="0.16" />
          {/* Jaw shadow — kept thin and faint so it doesn't read as a
              second chin. */}
          <path d="M120,194 Q150,210 180,194 Q150,201 120,194 Z" fill={SKIN_SHADE} opacity="0.2" />

          {/* Bangs + cap sit in front of the face — same lagged spring as
              the back hair, so the whole head of hair moves as one. */}
          {reduce ? (
            <g>
              <path d="M92,150 q2,-52 58,-52 q56,0 58,52 q-26,-30 -58,-30 q-32,0 -58,30 Z" fill="url(#nv-hair-grad)" />
              <path d="M110,96 q20,-14 40,-10" stroke={HAIR_LIGHT} strokeWidth="2.5" strokeLinecap="round" fill="none" opacity="0.5" />
              <path d="M190,96 q-20,-14 -40,-10" stroke={HAIR_LIGHT} strokeWidth="2" strokeLinecap="round" fill="none" opacity="0.35" />
              <g transform="translate(0,4)">
                <rect x="112" y="66" width="76" height="32" rx="11" fill="#ffffff" stroke={TINT_BORDER} strokeWidth="2" />
                <rect x="147.5" y="74" width="5" height="16" rx="2" fill={PRIMARY} />
                <rect x="142" y="79.5" width="16" height="5" rx="2" fill={PRIMARY} />
              </g>
            </g>
          ) : (
            <motion.g
              key={`bangs-${pose}`}
              style={{ transformBox: 'fill-box', transformOrigin: '50% 60%' }}
              initial={{ rotate: 4 }}
              animate={{ rotate: 0 }}
              transition={laggy}
            >
              {/* Bangs — painted over the forehead so the hairline reads
                  as continuous with the cap above it. */}
              <path
                d="M92,150 q2,-52 58,-52 q56,0 58,52 q-26,-30 -58,-30 q-32,0 -58,30 Z"
                fill="url(#nv-hair-grad)"
              />
              {/* Gloss strands on the crown */}
              <path d="M110,96 q20,-14 40,-10" stroke={HAIR_LIGHT} strokeWidth="2.5" strokeLinecap="round" fill="none" opacity="0.5" />
              <path d="M190,96 q-20,-14 -40,-10" stroke={HAIR_LIGHT} strokeWidth="2" strokeLinecap="round" fill="none" opacity="0.35" />
              {/* Nurse cap */}
              <g transform="translate(0,4)">
                <rect x="112" y="66" width="76" height="32" rx="11" fill="#ffffff" stroke={TINT_BORDER} strokeWidth="2" />
                <rect x="147.5" y="74" width="5" height="16" rx="2" fill={PRIMARY} />
                <rect x="142" y="79.5" width="16" height="5" rx="2" fill={PRIMARY} />
              </g>
            </motion.g>
          )}

          {/* Brows: raise while speaking, knit while thinking. */}
          <motion.g
            style={{ transformBox: 'fill-box', transformOrigin: 'center' }}
            animate={{ y: brow.y, rotate: brow.tilt }}
            transition={springy}
          >
            <path d="M114,139 q11,-6 22,-1" stroke={HAIR} strokeWidth="4" strokeLinecap="round" fill="none" />
          </motion.g>
          <motion.g
            style={{ transformBox: 'fill-box', transformOrigin: 'center' }}
            animate={{ y: brow.y, rotate: -brow.tilt }}
            transition={springy}
          >
            <path d="M164,138 q11,-5 22,1" stroke={HAIR} strokeWidth="4" strokeLinecap="round" fill="none" />
          </motion.g>

          {/* Eyes: iris gradient, dual catchlights, lash line; pupils
              track the pose target plus a small saccade jitter. */}
          <NurseEye cx={126} target={eyeTarget} blink={reduce ? false : blink} />
          <NurseEye cx={174} target={eyeTarget} blink={reduce ? false : blink} />

          {/* Blush + nose */}
          <ellipse cx="112" cy="180" rx="10" ry="7" fill="url(#nv-blush-grad)" />
          <ellipse cx="188" cy="180" rx="10" ry="7" fill="url(#nv-blush-grad)" />
          <path d="M147,170 q3,5 6,0" stroke={SKIN_SHADE} strokeWidth="3" strokeLinecap="round" fill="none" />

          {/* Mouth: shared viseme template — static shape at rest,
              continuously glides between visemes while speaking. */}
          {speaking ? (
            <path
              ref={mouthRef}
              d={buildMouthPath(MOUTH_VISEMES.closed)}
              fill={MOUTH_FILL}
              stroke={MOUTH_STROKE}
              strokeWidth={2.2}
              strokeLinejoin="round"
            />
          ) : (
            <path
              d={buildMouthPath(MOUTH_VISEMES[staticVisemeKey])}
              fill={MOUTH_FILL}
              stroke={MOUTH_STROKE}
              strokeWidth={2.2}
              strokeLinejoin="round"
            />
          )}
        </motion.g>

        {/* ── Clipboard (drawn raised — the writing pose) ───────────── */}
        <motion.g
          style={{ transformBox: 'fill-box', transformOrigin: '50% 50%' }}
          animate={PAD_POSES[pose]}
          transition={staggered}
        >
          <rect x="100" y="268" width="100" height="124" rx="10" fill={BOARD} stroke={BOARD_EDGE} strokeWidth="2" />
          <rect x="108" y="282" width="84" height="102" rx="6" fill={PAPER} />
          <rect x="132" y="260" width="36" height="15" rx="6" fill="#8f9bc4" />
          {/* Ruled lines */}
          {[300, 316, 332, 348, 364].map((y) => (
            <path key={y} d={`M116,${y} h68`} stroke={RULE} strokeWidth="3.5" strokeLinecap="round" />
          ))}
          {/* Ink appearing while she takes notes */}
          {[302, 318, 334].map((y, i) => (
            <motion.path
              key={y}
              d={`M116,${y} q5,-3 10,0 t10,0 t10,0 t10,0 t10,0`}
              stroke={INK}
              strokeWidth="2.5"
              strokeLinecap="round"
              fill="none"
              initial={{ pathLength: 0, opacity: 0 }}
              animate={
                listening
                  ? { pathLength: [0, 1, 1], opacity: [0.9, 0.9, 0] }
                  : { pathLength: 0, opacity: 0 }
              }
              transition={
                listening
                  ? {
                      duration: 3.9,
                      times: [0, 0.32, 1],
                      repeat: Infinity,
                      delay: i * 1.3,
                      ease: 'linear',
                    }
                  : { duration: 0.2 }
              }
            />
          ))}
          {/* Left hand steadying the board (rides with it) */}
          <circle cx="103" cy="336" r="9" fill="url(#nv-skin-grad)" />
        </motion.g>

        {/* ── Pen hand: scribbles on the paper, or lifts to the chin ── */}
        <g transform="translate(130,296)">
          <motion.g
            style={{ transformBox: 'fill-box', transformOrigin: '50% 50%' }}
            animate={
              listening
                ? { x: [0, 12, 22, 34, 44, 0], y: [0, 1.4, 0, 1.4, 0, 0], rotate: 0 }
                : HAND_POSES[pose]
            }
            transition={
              listening
                ? { duration: 1.3, repeat: Infinity, ease: 'linear' }
                : staggered
            }
          >
            {/* Pen (tip toward the paper) */}
            <path d="M-8,10 L13,-12" stroke={PRIMARY_DEEP} strokeWidth="5.5" strokeLinecap="round" />
            <circle cx="-8" cy="10" r="2.2" fill={MOUTH_FILL} />
            {/* Hand */}
            <circle cx="4" cy="-1" r="9.5" fill="url(#nv-skin-grad)" />
          </motion.g>
        </g>
      </motion.g>
    </svg>
  );
}
