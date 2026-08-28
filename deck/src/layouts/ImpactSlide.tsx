import { Block } from '../deck/Block';
import { MaliMark } from '../deck/MaliMark';
import { SlideHeadline } from '../deck/SlideHeadline';
import { Mark } from '../design-system/components/Mark';
import type { Slide } from '../content/types';

/**
 * What the hospital gets back, stated as a target rather than a finding.
 *
 * Every number here is a deployment assumption, so each carries its caveat in
 * the same breath — "a design target, not a measured result" sits inside the
 * card, not in a footnote nobody reads from eight metres. A hospital audience
 * will test this claim, and an admitted assumption survives that test where a
 * confident-looking figure does not.
 */
export function ImpactSlide({ slide }: { slide: Extract<Slide, { layout: 'impact' }> }) {
  return (
    <div className="d-impact">
      {/* A plain div, deliberately: Block is a motion element and framer writes
          its own `transform` on those, which would replace the CSS holding her
          in the corner. */}
      <div className="d-impact-mark">
        <span className="d-impact-bloom" aria-hidden="true" />
        <MaliMark size={280} />
      </div>

      <Block className="d-eyebrow">
        <Mark size={38} motion="budHand" />
        <span className="d-eyebrow-th" lang="th">
          {slide.eyebrow.th}
        </span>
        <span className="d-eyebrow-sep" aria-hidden="true">
          ·
        </span>
        <span className="d-eyebrow-en" lang="en">
          {slide.eyebrow.en}
        </span>
      </Block>

      <SlideHeadline headline={slide.headline} size="title" />

      <div className="d-impact-main">
        <Block className="d-impact-card">
          <span className="d-impact-card-label">{slide.card.label}</span>

          <span className="d-impact-figure">
            <span className="d-impact-prefix">{slide.card.prefix}</span>
            <strong>{slide.card.figure}</strong>
          </span>

          <span className="d-impact-card-th" lang="th">
            {slide.card.th}
          </span>
          <span className="d-impact-card-en" lang="en">
            {slide.card.en}
          </span>

          <span className="d-impact-second">
            <strong>{slide.card.secondary.figure}</strong>
            <span className="d-impact-second-body">
              <span className="d-impact-second-th" lang="th">
                {slide.card.secondary.th}
              </span>
              <span className="d-impact-second-en" lang="en">
                {slide.card.secondary.en}
              </span>
            </span>
          </span>
        </Block>

        <Block as="ol" className="d-impact-items">
          {slide.items.map((item, i) => (
            <li key={item.label}>
              <span className="d-impact-kicker">
                {String(i + 1).padStart(2, '0')} · {item.label}
              </span>
              <span className="d-impact-item-th" lang="th">
                {item.th}
              </span>
              <span className="d-impact-item-en" lang="en">
                {item.en}
              </span>
            </li>
          ))}
        </Block>
      </div>

      <Block className="d-impact-flow">
        {slide.flow.map((step, i) => (
          <span key={step.label} className="d-impact-step">
            {i > 0 && (
              <span className="d-impact-arrow" aria-hidden="true">
                →
              </span>
            )}
            <span className={step.strong ? 'is-strong' : undefined}>{step.label}</span>
          </span>
        ))}
      </Block>

      <Block className="d-impact-foot">
        <p className="d-impact-claim" lang="en">
          {slide.footer.claim}
        </p>
        <p className="d-impact-caveat" lang="en">
          {slide.footer.caveat}
        </p>
      </Block>
    </div>
  );
}
