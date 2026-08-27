import { Mark } from '../../design-system/components/Mark';
import type { VoiceCallState } from '../../hooks/useVoiceCall';

export type OrbState = VoiceCallState | 'idle';

interface AiOrbProps {
  state: OrbState;
  /** Diameter in px (the bud sits inside; ring extends to the edge). */
  size?: number;
  /** 0-1 mic/speaker level; drives the listening ring and speaking halo. */
  level?: number;
}

/**
 * MALI's presence in the conversation — the bud, alive (Brand v1.0).
 * Idle breathes; listening shows the teal ring; thinking spins a quiet dashed
 * ring; speaking pulses the gold halo. Styling lives in mali-components.css.
 */
export function AiOrb({ state, size = 132, level = 0.35 }: AiOrbProps) {
  const mali =
    state === 'speaking' ? 'speaking'
    : state === 'listening' ? 'listening'
    : state === 'thinking' || state === 'uploading' || state === 'starting' || state === 'greeting' ? 'thinking'
    : 'idle';
  return (
    <div
      className={`mali-orb mali-orb--${mali}`}
      style={{ width: size * 1.22, height: size * 1.22, ['--orb-level' as string]: level }}
      role="img"
      aria-label={`assistant ${state}`}
    >
      <span className="mali-orb__halo" aria-hidden="true" />
      <span className="mali-orb__ring" aria-hidden="true" />
      <span className="mali-orb__spin" aria-hidden="true" />
      <Mark className="mali-orb__bud" size={size * 0.68} />
    </div>
  );
}
