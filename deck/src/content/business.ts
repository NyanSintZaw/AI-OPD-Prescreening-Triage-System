/**
 * Slide 8's copy, split out because it is the densest slide in the deck and
 * inlining it made `slides.ts` hard to scan.
 *
 * Every figure here is an authored quote or a modelled estimate — none of it is
 * measured. That is why none of it lives in `facts.ts` (which demands a source)
 * or `fills.ts` (which chips missing numbers): they are neither. The caveats
 * travel with them instead, and the closing line says plainly that the pilot is
 * what turns any of it into a claim.
 */
import type { Slide } from './types';

type Business = Extract<Slide, { layout: 'business' }>;

export const BUSINESS_NOTE: Business['note'] = {
  title: 'Certified third-party medical devices.',
  body: "We integrate them. We don't manufacture them.",
};

export const BUSINESS_TIERS: Business['tiers'] = [
  {
    label: 'PILOT',
    title: 'Validate before committing',
    price: [{ figure: '฿75,000', unit: 'fixed · 3 months' }],
    lines: ['One station · hardware · criteria setup · training · baseline and impact measurement'],
    muted: 'Credited toward deployment, and it ends with a measured impact report',
  },
  {
    label: 'DEPLOY',
    title: 'Full implementation',
    badge: 'Main model',
    price: [
      { figure: '฿180,000', unit: 'one-time / station' },
      { figure: '+ ฿120,000', unit: 'per year · MALI license' },
    ],
    lines: ['Hardware ≈฿115,000 + device integration, installation, training'],
    muted: '฿540,000 over three years · license covers updates, tuning, support',
  },
  {
    label: 'MALI AS A SERVICE',
    title: 'No upfront capital cost',
    price: [{ figure: '฿16,000', unit: '/ month / station' }],
    lines: ['Hardware lease + software + maintenance + device replacement'],
    muted: '฿576,000 over three years · only ฿36,000 more than Deploy',
  },
];

export const BUSINESS_CASE: Business['businessCase'] = {
  label: 'THE BUSINESS CASE',
  title: 'Per station, at a target of 150 patients a day',
  muted: 'The pilot measures the real figures before we quote any of this as a claim.',
  stats: [
    {
      figure: '1,300',
      label: 'Nurse-hours released per year, target',
      tone: 'teal',
    },
    {
      figure: '฿325,000',
      label: 'Estimated capacity value',
      /* The distinction the whole slide turns on: released capacity is not
         cash until the hospital converts it. */
      muted: 'at ฿250 / nurse-hour — not cash savings',
      tone: 'teal',
    },
    {
      figure: '฿300,000',
      label: 'First-year cost, Deploy tier',
      muted: 'station + first-year license',
      tone: 'ink',
    },
  ],
  payback: {
    label: 'Payback, by share of released capacity converted',
    rows: [
      { share: '100%', months: '~11 mo' },
      { share: '70%', months: '~16 mo' },
      { share: '50%', months: '~22 mo' },
      { share: '30%', months: '~37 mo' },
    ],
  },
};

export const BUSINESS_CAVEAT =
  'Estimated pricing based on prototype hardware cost and an assumed nurse labour rate. Released nurse capacity is not the same as cash saved — only the share a hospital converts into reduced overtime or avoided hiring is a real saving, which is what the pilot measures.';
