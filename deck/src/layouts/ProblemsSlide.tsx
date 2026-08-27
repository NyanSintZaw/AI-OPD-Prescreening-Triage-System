import { Block } from '../deck/Block';
import { MaliMark } from '../deck/MaliMark';
import { SlideHeadline } from '../deck/SlideHeadline';
import { Mark } from '../design-system/components/Mark';
import type { Slide } from '../content/types';

/**
 * The four things that go wrong every day at the screening point.
 *
 * The list is a two-row grid filled column-major, so items 1 and 2 stack on
 * the left and 3 and 4 on the right — and, because they share rows, item 4's
 * top aligns with item 2's however many lines item 2's Thai runs to. Reading
 * order and visual order therefore agree, which a plain two-column float would
 * not guarantee.
 *
 * The eyebrow carries the bud rather than Nong Mali: the bud is the design
 * system's mark for small sizes, and she is reserved for greeting moments.
 */
export function ProblemsSlide({ slide }: { slide: Extract<Slide, { layout: 'problems' }> }) {
  return (
    <div className="d-problems">
      <span className="d-problems-bloom" aria-hidden="true" />

      <Block className="d-eyebrow">
        <Mark size={22} />
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

      <Block as="ul" className="d-problems-list">
        {slide.items.map((item) => (
          <li key={item.th}>
            <span className="d-problems-dot" aria-hidden="true" />
            <span className="d-problems-body">
              <span className="d-problems-th" lang="th">
                {item.th}
              </span>
              <span className="d-problems-en" lang="en">
                {item.en}
              </span>
            </span>
          </li>
        ))}
      </Block>

      {/* The right column's second item is short, which leaves a pocket in the
          bottom-right that the eye reads as unfinished. She fills it and
          balances the bloom in the opposite corner.

          A plain div, deliberately: Block is a motion element and framer
          writes its own `transform` on those, which would replace the CSS
          doing the positioning here. */}
      <div className="d-problems-mark">
        <MaliMark size={300} />
      </div>
    </div>
  );
}
