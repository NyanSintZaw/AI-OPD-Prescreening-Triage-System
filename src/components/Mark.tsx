import type { SVGProps } from 'react';

export interface MarkProps extends Omit<SVGProps<SVGSVGElement>, 'children'> {
  /** Pixel size of the square mark. */
  size?: number;
  /** `line` = single-colour stroke (headers, favicons). `glow` = gold + white fill with halo (kiosk idle, orb). */
  variant?: 'line' | 'glow';
}

/**
 * MALI mark — the no tuning orbit, reduced to one ring and one sparkle.
 * Use `line` everywhere except the kiosk idle screen.
 */
export function Mark({ size = 24, variant = 'line', ...rest }: MarkProps) {
  const glow = variant === 'glow';
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none" aria-hidden="true" {...rest}>
      {glow && <ellipse cx="25" cy="25" rx="16" ry="9" transform="rotate(-35 25 25)" fill="var(--gold-400)" opacity="0.9" />}
      <ellipse cx="25" cy="25" rx="16" ry="9" transform="rotate(-35 25 25)"
        stroke="currentColor" strokeWidth={glow ? 2.5 : 2} />
      <path d="M13 6.5c.7 2.6 1.9 3.8 4.5 4.5-2.6.7-3.8 1.9-4.5 4.5-.7-2.6-1.9-3.8-4.5-4.5 2.6-.7 3.8-1.9 4.5-4.5Z"
        fill={glow ? 'var(--gold-400)' : 'var(--color-accent)'} />
    </svg>
  );
}

export interface WordmarkProps {
  /** Rendered height of the wordmark in px. */
  height?: number;
  /** Show the product suffix after the mark. */
  product?: string;
}

/** `MALI.` — Anuphan semibold, gold period, optional product suffix ("Prescreening"). */
export function Wordmark({ height = 24, product }: WordmarkProps) {
  return (
    <span className="mali-wordmark" style={{ fontSize: height }}>
      <Mark size={height * 1.1} />
      <span className="mali-wordmark__name">MALI<span className="mali-wordmark__dot">.</span></span>
      {product && <span className="mali-wordmark__product">{product}</span>}
    </span>
  );
}
