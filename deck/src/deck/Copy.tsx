import type { ReactNode } from 'react';
import { FILLS } from '../content/fills';

const TOKEN = /\[\[([a-zA-Z0-9_]+)\]\]/g;

/**
 * Renders a copy string, resolving [[fillKey]] tokens against fills.ts.
 *
 * A token rather than typed slots: typed slots would give compile-time key
 * safety, but they shred every headline into a fragment array, and
 * readability is the only reason all the copy lives in one file. An unknown
 * key throws in dev and renders a plain chip in a build, so a typo surfaces
 * long before a projector does.
 */
export function Copy({ text, lang }: { text: string; lang?: 'th' | 'en' }) {
  const parts: ReactNode[] = [];
  let last = 0;
  let i = 0;

  for (const m of text.matchAll(TOKEN)) {
    const at = m.index ?? 0;
    if (at > last) parts.push(text.slice(last, at));
    parts.push(<Fill key={`f${i++}`} k={m[1]} />);
    last = at + m[0].length;
  }
  parts.push(text.slice(last));

  return <span lang={lang}>{parts}</span>;
}

/** One [FILL] slot: the number if we have it, an unmissable chip if we do not. */
export function Fill({ k }: { k: string }) {
  const f = FILLS[k];

  if (!f) {
    if (import.meta.env.DEV) throw new Error(`Unknown fill key: ${k}`);
    return <span className="d-fill">[FILL]</span>;
  }

  if (f.value == null) {
    return (
      <span className="d-fill" title={`${f.label} — ${f.source}`}>
        [FILL]
      </span>
    );
  }

  return (
    <span className="d-filled">
      {f.value}
      {f.unit ? ` ${f.unit}` : ''}
    </span>
  );
}
