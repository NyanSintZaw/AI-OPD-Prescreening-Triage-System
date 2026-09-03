import * as React from 'react';
import { NongMali, playMark, MARK_MOTIONS, type MarkMotion } from '@notuning/mali-ds';
const Wrap = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => <div className="mali-root" style={{ padding: 24, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', background: 'var(--surface-page)', ...style }}>{children}</div>;
export const Sizes = () => <Wrap style={{ gap: 32 }}><NongMali size={80} /><NongMali size={140} /></Wrap>;
export const Welcome = () => <Wrap style={{ justifyContent: 'center', padding: 40 }} ><div style={{ textAlign: 'center' }}><NongMali size={140} /><div style={{ fontSize: 24, fontWeight: 700, color: 'var(--text-heading)', marginTop: 16 }}>สวัสดีค่ะ ฉันชื่อมะลิ</div><div style={{ fontSize: 14, color: 'var(--text-muted)', marginTop: 6 }}>Hello, I'm Mali</div></div></Wrap>;

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
        <NongMali size={size} />
      </div>
      <figcaption style={{ textAlign: 'center' }}>
        <code style={{ fontSize: 'var(--text-xs)', color: 'var(--text-heading)', fontWeight: 'var(--fw-semibold)' }}>{motion}</code>
        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 2 }}>{MARK_MOTIONS[motion].role}</div>
      </figcaption>
    </figure>
  );
}

/** Her in-app entrances and idle loop — greeting moments, once per session. */
export const Entrances = () => (
  <Wrap style={{ gap: 24 }}>
    <Tile motion="nongRise" every={3600} />
    <Tile motion="nongWave" every={4200} />
    <Tile motion="nongBloom" every={6000} />
    <Tile motion="nongRiseSway" every={0} />
  </Wrap>
);

/** The attract loops — lobby-scale, they throw rings and petals and run forever. */
export const Attract = () => (
  <Wrap style={{ gap: 24 }}>
    <Tile motion="nongExplode" every={0} />
    <Tile motion="nongHeartbeat" every={0} />
    <Tile motion="nongWaveHello" every={0} />
    <Tile motion="nongBounce" every={0} />
  </Wrap>
);

/** nongShowreel sequences the other acts at random — the unattended kiosk loop. */
export const Showreel = () => (
  <Wrap style={{ gap: 24 }}>
    <Tile motion="nongShowreel" every={0} size={140} pad={140} />
  </Wrap>
);
