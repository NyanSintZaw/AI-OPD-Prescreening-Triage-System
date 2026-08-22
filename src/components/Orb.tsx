import { cx } from './cx';

export interface OrbProps {
  /** Voice state — the only thing that moves on the kiosk. */
  state?: 'idle' | 'listening' | 'thinking' | 'speaking';
  size?: number;
  /** 0–1 mic/speaker level; drives the listening/speaking ring. */
  level?: number;
}
/**
 * MALI's presence on the kiosk. Idle breathes slowly; listening rings expand with the mic level;
 * thinking spins the orbit; speaking pulses the halo. Reduced motion: static halo.
 */
export function Orb({ state = 'idle', size = 160, level = 0 }: OrbProps) {
  return (
    <div className={cx('mali-orb', `mali-orb--${state}`)} style={{ width: size, height: size, ['--orb-level' as string]: level }} role="img" aria-label={`MALI ${state}`}>
      <span className="mali-orb__ring" aria-hidden="true" />
      <span className="mali-orb__core" aria-hidden="true" />
      <svg className="mali-orb__orbit" viewBox="0 0 100 100" aria-hidden="true">
        <ellipse cx="50" cy="50" rx="44" ry="20" transform="rotate(-35 50 50)" stroke="var(--ink-900)" strokeWidth="3" fill="none" />
      </svg>
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
