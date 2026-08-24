import { cx } from './cx';
import { Mark } from './Mark';

export interface OrbProps {
  /** Voice state — the only thing that moves on the kiosk. */
  state?: 'idle' | 'listening' | 'thinking' | 'speaking';
  size?: number;
  /** 0-1 mic/speaker level; drives the listening ring and speaking halo. */
  level?: number;
}
/**
 * MALI's presence on the kiosk — the bud, alive. Idle breathes slowly; listening rings expand
 * with the mic level; thinking spins a quiet dashed ring; speaking pulses the gold halo.
 * Reduced motion: static bud. Nong Mali herself greets once via `NongMali`; this is the
 * in-conversation signal.
 */
export function Orb({ state = 'idle', size = 160, level = 0 }: OrbProps) {
  return (
    <div className={cx('mali-orb', `mali-orb--${state}`)} style={{ width: size, height: size, ['--orb-level' as string]: level }} role="img" aria-label={`MALI ${state}`}>
      <span className="mali-orb__halo" aria-hidden="true" />
      <span className="mali-orb__ring" aria-hidden="true" />
      <span className="mali-orb__spin" aria-hidden="true" />
      <Mark className="mali-orb__bud" size={size * 0.56} />
    </div>
  );
}

export interface KioskQuestionProps {
  /** The one question on screen. */
  question: string;
  /** Quiet caption — live transcript of what the patient said. */
  caption?: string;
  lang?: 'th' | 'en';
}
/** One question, centred, 40px. Nothing else competes with it. */
export function KioskQuestion({ question, caption, lang = 'th' }: KioskQuestionProps) {
  return (
    <div className="mali-kq" lang={lang}>
      <p className="mali-kq__q">{question}</p>
      {caption && <p className="mali-kq__caption">{caption}</p>}
    </div>
  );
}
