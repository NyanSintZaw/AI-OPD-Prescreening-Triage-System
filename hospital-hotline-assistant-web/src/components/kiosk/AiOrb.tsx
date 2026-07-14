import { motion, useReducedMotion } from 'framer-motion';
import { Mic, Sparkles } from 'lucide-react';
import type { VoiceCallState } from '../../hooks/useVoiceCall';

export type OrbState = VoiceCallState | 'idle';

interface AiOrbProps {
  state: OrbState;
  /** Diameter in px (the disc; the ring extends slightly beyond). */
  size?: number;
}

/**
 * The assistant's visual presence: a clean teal disc with one thin animated
 * ring. Breathes at rest, pulses faster while thinking, shows a mic while
 * listening and an equalizer while speaking. No glow — clinical modern.
 */
export function AiOrb({ state, size = 132 }: AiOrbProps) {
  const reduce = useReducedMotion();
  const speaking = state === 'speaking';
  const listening = state === 'listening';
  const thinking =
    state === 'thinking' || state === 'uploading' || state === 'starting' || state === 'greeting';

  const ringDuration = thinking ? 1.2 : listening ? 2 : 3.2;
  const iconSize = Math.round(size * 0.34);

  return (
    <div
      role="img"
      aria-label={`assistant ${state}`}
      style={{
        position: 'relative',
        width: size * 1.22,
        height: size * 1.22,
        display: 'grid',
        placeItems: 'center',
      }}
    >
      {/* Single thin ring */}
      <motion.span
        aria-hidden="true"
        style={{
          position: 'absolute',
          inset: 0,
          borderRadius: '50%',
          border: '2px solid rgba(63, 78, 135, 0.35)',
        }}
        animate={reduce ? undefined : { scale: [1, 1.07, 1], opacity: [0.8, 0.3, 0.8] }}
        transition={{ duration: ringDuration, repeat: Infinity, ease: 'easeInOut' }}
      />

      <motion.div
        style={{
          width: size,
          height: size,
          borderRadius: '50%',
          display: 'grid',
          placeItems: 'center',
          color: '#fff',
          background: 'linear-gradient(150deg, #8b9ac9 0%, #3f4e87 55%, #2d3963 100%)',
          boxShadow: '0 14px 34px -14px rgba(63, 78, 135, 0.55)',
        }}
        animate={
          reduce
            ? undefined
            : { scale: speaking ? [1, 1.05, 1] : listening ? [1, 1.03, 1] : [1, 1.015, 1] }
        }
        transition={{
          duration: speaking ? 0.7 : listening ? 1.8 : 3.4,
          repeat: Infinity,
          ease: 'easeInOut',
        }}
      >
        {speaking ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, height: iconSize }} aria-hidden="true">
            {[0, 1, 2, 3, 4].map((i) => (
              <motion.span
                key={i}
                style={{ width: 5, borderRadius: 3, background: '#fff', height: 12 }}
                animate={reduce ? undefined : { height: [10, iconSize * 0.9, 10] }}
                transition={{ duration: 0.6, repeat: Infinity, ease: 'easeInOut', delay: i * 0.1 }}
              />
            ))}
          </div>
        ) : listening ? (
          <Mic size={iconSize} strokeWidth={2.2} aria-hidden="true" />
        ) : (
          <Sparkles size={iconSize} strokeWidth={2} aria-hidden="true" />
        )}
      </motion.div>
    </div>
  );
}
