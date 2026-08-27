import { Block } from '../deck/Block';
import { SlideHeadline } from '../deck/SlideHeadline';
import { Mark } from '../design-system/components/Mark';
import type { Slide } from '../content/types';

/**
 * What the pilot has to prove, and how it will be judged.
 *
 * The argument sits left, the measurements right. Every KPI is captured on both
 * sides of the change — that repetition is the credibility of the slide, not
 * padding, because it shows the metrics were fixed before the results existed.
 */
export function PilotSlide({ slide }: { slide: Extract<Slide, { layout: 'pilot' }> }) {
  return (
    <div className="d-pilot">
      <div className="d-pilot-left">
        <Block className="d-eyebrow">
          <Mark size={20} />
          <span className="d-eyebrow-en" lang="en">
            {slide.eyebrow.en}
          </span>
        </Block>

        <SlideHeadline headline={slide.headline} size="title" />

        <Block>
          <p className="d-pilot-lead" lang="en">
            {slide.lead}
          </p>
        </Block>

        <Block className="d-pilot-outcome">
          <span className="d-pilot-outcome-label">{slide.outcome.label}</span>
          <strong>{slide.outcome.title}</strong>
          <span className="d-pilot-outcome-body">{slide.outcome.body}</span>
        </Block>
      </div>

      <Block as="section" className="d-pilot-table">
        <div className="d-pilot-row is-head">
          <span>{slide.table.columns[0]}</span>
          <span>{slide.table.columns[1]}</span>
          <span>{slide.table.columns[2]}</span>
        </div>
        {slide.table.rows.map((r) => (
          <div key={r.kpi} className="d-pilot-row">
            <span className="d-pilot-kpi">{r.kpi}</span>
            <span className="d-pilot-before">{r.before}</span>
            <span className="d-pilot-during">{r.during}</span>
          </div>
        ))}
      </Block>
    </div>
  );
}
