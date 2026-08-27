import { Block } from '../deck/Block';
import { SlideHeadline } from '../deck/SlideHeadline';
import { Mark } from '../design-system/components/Mark';
import type { Slide } from '../content/types';

/**
 * How the hospital buys this, and what it gets back.
 *
 * English-only, deliberately: the commercial half of the pitch is delivered in
 * English because that is the language procurement reads contracts in. The
 * headline opts into that with `lead: 'en'` rather than quietly omitting Thai.
 *
 * Every figure is a quote or a model, not a measurement, so each block keeps
 * its qualifier — and the footer says the thing that matters most, which is
 * that released nurse capacity only becomes money if the hospital converts it.
 * Pricing slides fail when they let an estimate look like a finding.
 */
export function BusinessSlide({ slide }: { slide: Extract<Slide, { layout: 'business' }> }) {
  const { businessCase: bc } = slide;

  return (
    <div className="d-business">
      <span className="d-business-bloom" aria-hidden="true" />

      <div className="d-business-head">
        <div>
          <Block className="d-eyebrow">
            <Mark size={20} />
            <span className="d-eyebrow-en" lang="en">
              {slide.eyebrow.en}
            </span>
          </Block>

          <SlideHeadline headline={slide.headline} size="title" />

          <Block>
            <p className="d-business-sub" lang="en">
              {slide.subtitle}
            </p>
          </Block>
        </div>

        {/* Answers "do you make the devices?" before it is asked. */}
        <Block className="d-business-note">
          <span className="d-business-note-title">{slide.note.title}</span>
          <span className="d-business-note-body">{slide.note.body}</span>
        </Block>
      </div>

      <Block as="ol" className="d-business-tiers">
        {slide.tiers.map((tier, i) => (
          <li key={tier.label} className={tier.badge ? 'is-main' : undefined}>
            {tier.badge && <span className="d-business-badge">{tier.badge}</span>}

            <span className="d-business-kicker">
              {String(i + 1).padStart(2, '0')} · {tier.label}
            </span>
            <span className="d-business-title">{tier.title}</span>

            {tier.price.map((p) => (
              <span key={p.figure} className="d-business-price">
                <strong>{p.figure}</strong>
                <em>{p.unit}</em>
              </span>
            ))}

            <span className="d-business-lines">
              {tier.lines.map((l) => (
                <span key={l}>{l}</span>
              ))}
              <span className="d-business-muted">{tier.muted}</span>
            </span>
          </li>
        ))}
      </Block>

      <Block className="d-business-case">
        <div className="d-business-case-intro">
          <span className="d-business-case-label">{bc.label}</span>
          <span className="d-business-case-title">{bc.title}</span>
          <span className="d-business-muted">{bc.muted}</span>
        </div>

        {bc.stats.map((stat) => (
          <div key={stat.figure} className="d-business-stat">
            <strong className={`is-${stat.tone ?? 'teal'}`}>{stat.figure}</strong>
            <span className="d-business-stat-label">{stat.label}</span>
            {stat.muted && <span className="d-business-muted">{stat.muted}</span>}
          </div>
        ))}

        <div className="d-business-payback">
          <span className="d-business-payback-label">
            <span className="d-business-dot" aria-hidden="true" />
            {bc.payback.label}
          </span>
          <div className="d-business-payback-grid">
            {bc.payback.rows.map((r) => (
              <span key={r.share}>
                <strong>{r.share}</strong>
                <em aria-hidden="true">→</em>
                <b>{r.months}</b>
              </span>
            ))}
          </div>
        </div>
      </Block>

      <Block>
        <p className="d-business-caveat" lang="en">
          {slide.caveat}
        </p>
      </Block>
    </div>
  );
}
