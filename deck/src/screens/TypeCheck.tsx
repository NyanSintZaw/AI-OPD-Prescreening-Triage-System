import { QA } from '../content/qa';
import { SLIDES } from '../content/slides';

/**
 * Every Thai string in the deck, at the size and on the surface it actually
 * renders at, on one screen.
 *
 * This exists for one job PITCH_DECK insists on and nothing else can do: read
 * it from the back of the actual room, on the actual projector. Thai tone
 * marks and lower vowels are the first thing to disappear at low contrast, and
 * they disappear at projector scale rather than at 100% in a browser — so the
 * check has to happen on a page that shows them all together, scaled.
 *
 * Two rules it is here to catch: no Thai below 28px on the 1920 stage, and no
 * Thai body text in a muted colour.
 */
type Sample = { text: string; where: string; px: number };

function samples(): Sample[] {
  const out: Sample[] = [];

  for (const s of SLIDES) {
    const headPx =
      s.layout === 'hero'
          ? 86
          : s.layout === 'problems'
            ? 76
            : s.layout === 'solution'
              ? 50
              : s.layout === 'impact'
                ? 58
                : 96;
    if (s.headline.th) {
      out.push({ text: s.headline.th, where: `${s.id} — headline`, px: headPx });
    }

    if (s.layout === 'problems') {
      out.push({ text: s.eyebrow.th, where: `${s.id} — eyebrow`, px: 28 });
      s.items.forEach((it) => out.push({ text: it.th, where: `${s.id} — item`, px: 34 }));
    }
    if (s.layout === 'impact') {
      out.push({ text: s.eyebrow.th, where: `${s.id} — eyebrow`, px: 30 });
      out.push({ text: s.card.th, where: `${s.id} — card`, px: 30 });
      out.push({ text: s.card.secondary.th, where: `${s.id} — card secondary`, px: 28 });
      s.items.forEach((it) => out.push({ text: it.th, where: `${s.id} — item`, px: 30 }));
    }

    if (s.layout === 'solution') {
      out.push({ text: s.eyebrow.th, where: `${s.id} — eyebrow`, px: 30 });
      out.push({ text: s.brand.th, where: `${s.id} — brand`, px: 28 });
      s.items.forEach((it) => out.push({ text: it.th, where: `${s.id} — item`, px: 33 }));
    }
    if (s.layout === 'hero') {
      out.push({ text: s.stats.total.label, where: `${s.id} — total`, px: 26 });
      s.stats.split.forEach((b) => out.push({ text: b.label, where: `${s.id} — bar`, px: 23 }));
      out.push({ text: s.stats.hero.label, where: `${s.id} — hero`, px: 32 });
      out.push({ text: s.stats.source, where: `${s.id} — source`, px: 19 });
    }
    /* The cover carries no Thai — it is a brand lockup. */
  }

  for (const e of QA) {
    out.push({ text: e.q.th, where: 'qa — question', px: 24 });
    out.push({ text: e.a.th, where: 'qa — answer', px: 18 });
  }

  /* Render the chip text, not the raw token: the string on the slide reads
     "[FILL]", and a check of how Thai sets around it should measure that. */
  return out
    .map((s) => ({ ...s, text: s.text.replace(/\[\[[a-zA-Z0-9_]+\]\]/g, '[FILL]') }))
    .filter((s) => /[฀-๿]/.test(s.text));
}

export function TypeCheck() {
  const rows = samples();
  const tooSmall = rows.filter((r) => r.px < 28).length;

  return (
    <div className="d-screen d-typecheck">
      <h1 className="d-screen-title">Thai type check</h1>
      <p className="d-screen-lead">
        {rows.length} Thai strings at their real sizes. Read this from the back of the room on
        the actual projector. {tooSmall} are under 28px — those are the ones that decide it.
      </p>

      <div className="d-typecheck-rows">
        {rows.map((r, i) => (
          <div key={`${r.where}-${i}`} className={`d-typecheck-row${r.px < 28 ? ' is-small' : ''}`}>
            <span className="d-typecheck-where">
              {r.where} · {r.px}px
            </span>
            <span className="d-typecheck-text" lang="th" style={{ fontSize: r.px, lineHeight: 1.4 }}>
              {r.text}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
