import { Block } from '../deck/Block';
import { MaliMark } from '../deck/MaliMark';
import { useDeckMotionContext } from '../deck/motionContext';
import type { Slide } from '../content/types';
import notuning from '../assets/notuning.png';

/**
 * The slide that plays while the room fills.
 *
 * A centred brand lockup rather than a headline slide — which is why this is
 * the one layout that does not call <SlideHeadline>. The mark, the wordmark,
 * the backronym, and who built it. The slide's `headline` stays in the data as
 * the label the overview grid and the notes panel show.
 *
 * Nong Mali runs `nongShowreel` — the attract mixer the booth itself runs, so
 * the first thing the audience sees is literally the product's own idle loop.
 * Her stage is roughly twice the mark because the motion throws rings and
 * petals into the parent as DOM nodes, and a tight parent clips them.
 *
 * She appears here and on the closing slide and nowhere else: two greeting
 * moments bracketing the talk, which is what the brand guide means by "once
 * per session, never looping decoration".
 */
export function CoverSlide({ slide }: { slide: Extract<Slide, { layout: 'cover' }> }) {
  const motion = useDeckMotionContext();

  return (
    <div className="d-cover">
      <Block className="d-cover-mark">
        <MaliMark size={240} />
      </Block>

      <Block>
        <h1 className="d-cover-wordmark">
          {slide.wordmark.name}
          <span className="d-cover-accent">{slide.wordmark.accent}</span>
          {slide.wordmark.product}
        </h1>
      </Block>

      <Block>
        <p className="d-cover-tagline">{slide.tagline}</p>
      </Block>

      <Block className="d-cover-team">
        <span className="d-cover-rule" aria-hidden="true" />
        <span className="d-cover-team-label">{slide.team.label}</span>
        {/* The team mark is white-on-transparent, built for dark surfaces, so
            it sits on its own deep-leaf plate rather than vanishing into the
            paper. */}
        <span className="d-cover-team-plate">
          <img src={notuning} alt={slide.team.name} />
        </span>
        <span className="d-cover-rule" aria-hidden="true" />
      </Block>

      {motion?.prefersReduced && !motion.forced && (
        <Block className="d-cover-motionwarn">
          Reduced motion is on for this machine — press M to force motion before you present.
        </Block>
      )}
    </div>
  );
}
