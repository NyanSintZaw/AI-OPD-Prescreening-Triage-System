import { Block } from '../deck/Block';
import { MaliMark } from '../deck/MaliMark';
import type { Slide } from '../content/types';

/**
 * A hold screen — the slides stop here and something else happens.
 *
 * Deep teal and full bleed, because that is what dark means in this deck. Both
 * the demo hand-off and the Q&A close are the same object, so they share this
 * layout rather than drifting apart as two near-identical components.
 *
 * The mark is optional: the demo screen carries none, the closing screen
 * carries her large and cycling. She is fixed-palette by brand rule, so on the
 * deep ground her silhouette is lifted by a pale bloom behind her rather than
 * by any change to the artwork.
 */
export function HoldSlide({ slide }: { slide: Extract<Slide, { layout: 'hold' }> }) {
  return (
    <div className={`d-hold${slide.mark ? ' has-mark' : ''}`}>
      {slide.mark && (
        <div className="d-hold-mark">
          <span className="d-hold-bloom" aria-hidden="true" />
          <MaliMark size={slide.mark.size} cycle={slide.mark.cycle} />
        </div>
      )}

      <Block>
        <p className="d-hold-label">{slide.label}</p>
      </Block>
      <Block>
        <p className="d-hold-sub" lang="th">
          {slide.sub}
        </p>
      </Block>
    </div>
  );
}
