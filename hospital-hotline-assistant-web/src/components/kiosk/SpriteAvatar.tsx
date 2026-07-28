import { useEffect, useMemo, useState } from 'react';
import { useReducedMotion } from 'framer-motion';
import type { VoiceCallState } from '../../hooks/useVoiceCall';
import { NurseAvatar } from './NurseAvatar';

type AvatarPose = 'idle' | 'listening' | 'thinking' | 'speaking';

interface SpriteManifest {
  canvas: [number, number];
  states: Record<string, string[]>;
}

interface SpriteAvatarProps {
  state: VoiceCallState | 'idle';
  /** Live loudness of the assistant's voice (0..1) — picks the mouth
   *  frame while speaking. Must be identity-stable (useVoiceCall.getOutputLevel). */
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

// Loop definition per pose: which manifest state feeds it and how fast.
const POSE_LOOPS: Record<Exclude<AvatarPose, 'speaking'>, { state: string; fps: number }> = {
  idle: { state: 'idle', fps: 4 },
  listening: { state: 'write', fps: 6 },
  thinking: { state: 'think', fps: 4 },
};

// Mouth thresholds for speaking (smoothed 0..1 loudness → frame set).
const TALK_MID_AT = 0.08;
const TALK_OPEN_AT = 0.35;
const TALK_HOLD_MS = 70;

const FRAME_BASE = '/avatar/';

/**
 * Frame-based (flipbook) avatar: plays per-state loops of real artwork
 * frames processed by scripts/process_avatar_frames.py into
 * public/avatar/. Speaking picks between talk_closed / talk_mid /
 * talk_open frames from the live TTS loudness — lip sync with the
 * actual approved art. Falls back to the code-drawn NurseAvatar until
 * frames exist or if loading fails, so the tile is never empty.
 */
export function SpriteAvatar({ state, getLevel }: SpriteAvatarProps) {
  const reduce = useReducedMotion();
  const pose = toPose(state);

  const [manifest, setManifest] = useState<SpriteManifest | null>(null);
  const [failed, setFailed] = useState(false);
  const [frame, setFrame] = useState<string | null>(null);

  // ── Load manifest + preload every frame once ─────────────────────────
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${FRAME_BASE}manifest.json`, { cache: 'no-cache' });
        if (!res.ok) throw new Error(`manifest ${res.status}`);
        const data = (await res.json()) as SpriteManifest;
        const all = Object.values(data.states ?? {}).flat();
        if (!all.length) throw new Error('manifest has no frames');
        await Promise.all(
          all.map(
            (name) =>
              new Promise<void>((resolve, reject) => {
                const img = new Image();
                img.onload = () => resolve();
                img.onerror = () => reject(new Error(`failed to load ${name}`));
                img.src = FRAME_BASE + name;
              }),
          ),
        );
        if (!cancelled) setManifest(data);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const states = manifest?.states;

  // Frames for the current pose, with graceful degradation when a set
  // is missing (e.g. no think frames yet → fall back to idle frames).
  const loopFrames = useMemo(() => {
    if (!states) return [];
    if (pose === 'speaking') return states.talk_closed ?? states.idle ?? [];
    const want = POSE_LOOPS[pose].state;
    return states[want] ?? states.idle ?? [];
  }, [states, pose]);

  // ── Loop player (idle / listening / thinking) ────────────────────────
  useEffect(() => {
    if (!states || pose === 'speaking' || loopFrames.length === 0) return;
    setFrame(loopFrames[0]);
    if (reduce || loopFrames.length === 1) return;

    let i = 0;
    let timer = 0;
    const stepMs = 1000 / POSE_LOOPS[pose].fps;
    const start = () => {
      window.clearInterval(timer);
      timer = window.setInterval(() => {
        i = (i + 1) % loopFrames.length;
        setFrame(loopFrames[i]);
      }, stepMs);
    };
    // The kiosk runs 24/7 — don't burn timers while the tab is hidden.
    const onVis = () => {
      if (document.hidden) window.clearInterval(timer);
      else start();
    };
    start();
    document.addEventListener('visibilitychange', onVis);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVis);
    };
  }, [states, pose, loopFrames, reduce]);

  // ── Blink overlay (idle + listening) ─────────────────────────────────
  // Briefly swaps in a blink frame; the loop player resumes on its next
  // tick. write_blink is preferred while writing when provided.
  useEffect(() => {
    if (!states || reduce) return;
    const blinkSet =
      pose === 'listening' ? states.write_blink ?? states.blink : pose === 'idle' ? states.blink : null;
    if (!blinkSet?.length) return;
    let openTimer = 0;
    let closeTimer = 0;
    const schedule = () => {
      openTimer = window.setTimeout(() => {
        setFrame(blinkSet[0]);
        closeTimer = window.setTimeout(schedule, 130);
      }, 2800 + Math.random() * 3200);
    };
    schedule();
    return () => {
      window.clearTimeout(openTimer);
      window.clearTimeout(closeTimer);
    };
  }, [states, pose, reduce]);

  // ── Speaking: amplitude → mouth frame ────────────────────────────────
  useEffect(() => {
    if (!states || pose !== 'speaking') return;
    const closed = states.talk_closed ?? states.idle ?? [];
    const mid = states.talk_mid ?? [];
    const open = states.talk_open ?? mid;
    if (!closed.length && !open.length) return;

    if (reduce || !getLevel) {
      setFrame((closed[0] ?? open[0]) as string);
      return;
    }

    let raf = 0;
    let smoothed = 0;
    let lastSwap = 0;
    let current = '';
    const pick = (level: number, variant: number): string | undefined => {
      const set = level >= TALK_OPEN_AT && open.length ? open : level >= TALK_MID_AT && (mid.length || open.length) ? (mid.length ? mid : open) : closed;
      return set.length ? set[variant % set.length] : undefined;
    };
    const tick = (now: number) => {
      const target = getLevel();
      smoothed += (target - smoothed) * (target > smoothed ? 0.5 : 0.22);
      if (now - lastSwap >= TALK_HOLD_MS) {
        const next = pick(smoothed, Math.floor(now / 400));
        if (next && next !== current) {
          current = next;
          lastSwap = now;
          setFrame(next);
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [states, pose, reduce, getLevel]);

  // ── Render ───────────────────────────────────────────────────────────
  if (failed || !frame) {
    // Loading or no frames shipped yet → the code-drawn nurse fills in.
    return <NurseAvatar state={state} getLevel={getLevel} />;
  }

  return (
    <img
      src={FRAME_BASE + frame}
      alt={`assistant ${state}`}
      draggable={false}
      style={{ userSelect: 'none' }}
    />
  );
}
