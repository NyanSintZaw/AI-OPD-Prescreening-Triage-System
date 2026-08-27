import { motion } from 'framer-motion';
import type { Headline } from '../content/types';
import { Copy } from './Copy';
import { useReveal } from './motionContext';

/**
 * The ONLY place a slide title is typeset.
 *
 * Thai large, English small underneath. PITCH_DECK §0: "pick one and never
 * flip it." There is no prop that reverses the order, and `Headline` carries
 * no lead discriminator, so "English big" is not expressible anywhere in the
 * deck. Two exceptions, both explicit: the cover, which is a brand lockup and
 * sets the MALI wordmark itself, and a headline carrying `lead: 'en'`, which
 * the commercial section uses because PITCH_DECK §0 puts that half of the pitch
 * in English on purpose — it is the language procurement reads contracts in.
 *
 * `accent` sets a phrase apart. It is highlighted only when it occurs exactly
 * once in the Thai — a phrase appearing twice is left alone rather than
 * guessed at, so the wrong occurrence can never light up. `accentTone` picks
 * whether it pulls the eye (teal) or recedes (muted).
 */
export function SlideHeadline({
  headline,
  size = 'display',
  tone = 'light',
}: {
  headline: Headline;
  size?: 'display' | 'title';
  /** `dark` for the deep-leaf cue cards. */
  tone?: 'light' | 'dark';
}) {
  const reveal = useReveal();
  const { th, en, accent, accentTone = 'teal', lead } = headline;
  const leadsEn = lead === 'en';
  /* Whichever language leads is the one the accent is matched against. */
  const body = leadsEn ? en : (th ?? en);
  const at = accent ? body.indexOf(accent) : -1;
  const once = at !== -1 && body.indexOf(accent!, at + 1) === -1;
  const [head, tail] = once
    ? [body.slice(0, at), body.slice(at + accent!.length)]
    : [body, ''];

  return (
    <motion.hgroup
      className={`d-headline d-headline--${size}${tone === 'dark' ? ' is-dark' : ''}`}
      variants={reveal}
    >
      <h1 className="d-th" lang={leadsEn ? 'en' : 'th'}>
        <Copy text={head} lang={leadsEn ? 'en' : 'th'} />
        {once && <span className={`d-th-accent d-th-accent--${accentTone}`}>{accent}</span>}
        {tail && <Copy text={tail} lang={leadsEn ? 'en' : 'th'} />}
      </h1>
      {!leadsEn && (
        <p className="d-en" lang="en">
          <Copy text={en} lang="en" />
        </p>
      )}
    </motion.hgroup>
  );
}
