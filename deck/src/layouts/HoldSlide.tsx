import { Block } from '../deck/Block';
import { MaliMark } from '../deck/MaliMark';
import type { Slide } from '../content/types';
import notuning from '../assets/notuning.png';

/**
 * A hold screen — the slides stop here and something else happens.
 *
 * A light teal wash, full bleed. Both the demo hand-off and the Q&A close are
 * the same object, so they share this layout rather than drifting apart as two
 * near-identical components.
 *
 * The mark is optional: the demo screen carries none, the closing screen
 * carries her large and cycling. She is fixed-palette by brand rule, which is
 * exactly why this ground is light — on the deep teal it used to be, her teal
 * body sank into the background and needed a glow behind it to read at all.
 */
export function HoldSlide({ slide }: { slide: Extract<Slide, { layout: 'hold' }> }) {
  return (
    <div className={`d-hold${slide.mark ? ' has-mark' : ''}`}>
      {slide.mark && (
        <div className="d-hold-mark">
          <MaliMark size={slide.mark.size} motion={slide.mark.motion} acts={slide.mark.acts} />
        </div>
      )}

      <Block>
        <p className="d-hold-label">
          {typeof slide.label === 'string' ? (
            slide.label
          ) : (
            <>
              {slide.label.lead}
              <span className="d-hold-accent">{slide.label.accent}</span>
              {slide.label.tail}
            </>
          )}
        </p>
      </Block>
      <Block>
        <p className="d-hold-sub" lang="th">
          {slide.sub}
        </p>
      </Block>

      {/* Out of the centred column entirely, so it can sit under a headline
          for ten minutes without ever reading as part of it. */}
      {slide.team && (
        <Block className="d-hold-team">
          <span className="d-hold-team-label">{slide.team.label}</span>
          <span className="d-hold-team-plate">
            <img src={notuning} alt={slide.team.name} />
          </span>
        </Block>
      )}
    </div>
  );
}
