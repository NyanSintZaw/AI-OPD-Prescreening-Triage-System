import { Block } from '../deck/Block';
import { MaliMark } from '../deck/MaliMark';
import { SlideHeadline } from '../deck/SlideHeadline';
import type { Slide } from '../content/types';
import { WalkinStats } from '../visuals/WalkinStats';
import { BusinessSlide } from './BusinessSlide';
import { CoverSlide } from './CoverSlide';
import { HoldSlide } from './HoldSlide';
import { ImpactSlide } from './ImpactSlide';
import { ChecklistSlide } from './ChecklistSlide';
import { PilotSlide } from './PilotSlide';
import { ProblemsSlide } from './ProblemsSlide';
import { SolutionSlide } from './SolutionSlide';

/**
 * Dispatch on the layout discriminant. Adding a layout is a compile-time
 * event: the union in content/types.ts makes an unhandled case a type error
 * rather than a blank slide discovered in a rehearsal.
 */
export function SlideView({ slide }: { slide: Slide }) {
  switch (slide.layout) {
    case 'cover':
      return <CoverSlide slide={slide} />;

    case 'hold':
      return <HoldSlide slide={slide} />;

    case 'hero':
      return (
        <div className="d-hero">
          <div className="d-hero-head">
            <SlideHeadline headline={slide.headline} />
          </div>

          {/* She sits in the negative space the ragged right edge of the Thai
              leaves, not below it — high enough to read as part of the
              sentence rather than a mascot parked in a corner.

              A plain div, deliberately: Block is a motion element, and framer
              writes its own `transform` on those, which silently replaces the
              CSS translateY(-50%) doing the centring here. She has her own
              attract loop; she does not need the reveal stagger too. */}
          <div className="d-hero-mark">
            <span className="d-hero-glow" aria-hidden="true" />
            <MaliMark size={380} />
          </div>

          <Block className="d-hero-evidence">
            <WalkinStats stats={slide.stats} />
          </Block>
        </div>
      );

    case 'problems':
      return <ProblemsSlide slide={slide} />;

    case 'solution':
      return <SolutionSlide slide={slide} />;

    case 'impact':
      return <ImpactSlide slide={slide} />;

    case 'checklist':
      return <ChecklistSlide slide={slide} />;

    case 'business':
      return <BusinessSlide slide={slide} />;

    case 'pilot':
      return <PilotSlide slide={slide} />;

  }
}
