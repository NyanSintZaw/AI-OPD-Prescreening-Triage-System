import * as React from 'react';
import { Mark, playMark, MARK_MOTIONS, type MarkMotion } from '@notuning/mali-ds';
const Wrap = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => <div className="mali-root" style={{ padding: 24, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', background: 'var(--surface-page)', ...style }}>{children}</div>;
export const Sizes = () => <Wrap style={{ gap: 24 }}><Mark size={24} /><Mark size={48} /><Mark size={96} /></Wrap>;
export const Stages = () => <Wrap style={{ gap: 24 }}><Mark size={64} stage={0} /><Mark size={64} stage={1} /><Mark size={64} stage={3} /></Wrap>;

/* A showcase tile, so `force: true`: these cards exist to show the motions, and
   under prefers-reduced-motion playMark would otherwise schedule nothing.
   `every` is the replay period for the one-shots; the attract loops and
   nongRiseSway repeat on their own, so they pass 0. */
function Tile({ motion, every, size = 96, pad = 64 }: { motion: MarkMotion; every: number; size?: number; pad?: number }) {
  const ref = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    let h: { cancel: () => void } | undefined;
    const play = () => { h?.cancel(); h = playMark(ref.current, motion, { force: true }); };
    const raf = requestAnimationFrame(play);
    const id = every ? setInterval(play, every) : undefined;
    return () => { cancelAnimationFrame(raf); if (id) clearInterval(id); h?.cancel(); };
  }, [motion, every]);
  return (
    <figure style={{ margin: 0, width: size + pad + 16, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 'var(--space-2)' }}>
      {/* The attract loops throw rings and petals into this box — playMark's
          stage is the mark's parent. Clipped so a lobby-scale effect stays in
          its own tile instead of drawing over the neighbour's caption. */}
      <div ref={ref} style={{ position: 'relative', overflow: 'hidden', display: 'grid', placeItems: 'center', inlineSize: size + pad, blockSize: size + pad }}>
        <Mark size={size} />
      </div>
      <figcaption style={{ textAlign: 'center' }}>
        <code style={{ fontSize: 'var(--text-xs)', color: 'var(--text-heading)', fontWeight: 'var(--fw-semibold)' }}>{motion}</code>
        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 2 }}>{MARK_MOTIONS[motion].role}</div>
      </figcaption>
    </figure>
  );
}

/** The bud's four approved loading/progress motions. */
export const Motion = () => (
  <Wrap style={{ gap: 24 }}>
    <Tile motion="budDraw" every={3200} size={72} />
    <Tile motion="budFilled" every={3200} size={72} />
    <Tile motion="budHand" every={4200} size={72} />
    <Tile motion="budGrow" every={2400} size={72} />
  </Wrap>
);
