import { Block } from '../deck/Block';
import { MaliMark } from '../deck/MaliMark';
import { SlideHeadline } from '../deck/SlideHeadline';
import { Mark } from '../design-system/components/Mark';
import type { Slide } from '../content/types';

/**
 * Who MALI is, and the four things she does.
 *
 * A brand column on the left and the argument on the right. She is introduced
 * here as a colleague rather than a feature, so the left column is her
 * lockup — mark, name, and what the name stands for — at a scale that lets
 * her hold half the slide on her own.
 *
 * The numbers are rendered from position rather than authored, so reordering
 * the items in `slides.ts` cannot leave 03 sitting above 02.
 */
export function SolutionSlide({ slide }: { slide: Extract<Slide, { layout: 'solution' }> }) {
  return (
    <div className="d-solution">
      <div className="d-solution-brand">
        {/* Out of flow relative to its own box, so the attract loop's rings and
            petals overflow freely without moving the lockup below them. */}
        <div className="d-solution-mark">
          <span className="d-solution-glow" aria-hidden="true" />
          <MaliMark size={270} />
        </div>

        <Block>
          <p className="d-solution-wordmark">
            {slide.brand.name}
            <span className="d-solution-accent">{slide.brand.accent}</span>I
          </p>
          <p className="d-solution-brand-th" lang="th">
            {slide.brand.th}
          </p>
          <p className="d-solution-brand-en" lang="en">
            {slide.brand.en}
          </p>
        </Block>
      </div>

      <div className="d-solution-body">
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

        <Block as="ol" className="d-solution-list">
          {slide.items.map((item, i) => (
            <li key={item.th}>
              <span className="d-solution-n" aria-hidden="true">
                {String(i + 1).padStart(2, '0')}
              </span>
              <span className="d-solution-item">
                <span className="d-solution-th" lang="th">
                  {item.th}
                </span>
                <span className="d-solution-en" lang="en">
                  {item.en}
                </span>
              </span>
            </li>
          ))}
        </Block>
      </div>
    </div>
  );
}
