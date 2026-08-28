/**
 * The deck's content model.
 *
 * The rule from PITCH_DECK.md §0 that matters most is encoded here as a type
 * rather than left to a review checklist, because it is the kind of thing that
 * survives review and then fails on a projector: Thai leads. `Headline` carries
 * `th` and `en` with no field that reverses them, so "English big" is only
 * reachable by setting `lead: 'en'` on purpose — which the commercial and
 * deployment slides do, because that half of the pitch is delivered in English.
 */
import type { MarkMotion, ShowreelAct } from '../deck/MaliMark';
import type { FactKey } from './facts';

/** Which presenter owns the slide — PITCH_DECK §0's two-presenter table. */
export type Presenter = 'TH' | 'EN';

export type SectionId = 'cover' | 'problem' | 'demo' | 'business' | 'deployment' | 'ask';

/** Thai large, English small underneath. Pick one and never flip it. */
export interface Headline {
  /** May contain 
 where the line must break on a beat rather than on width.
   *  Optional ONLY alongside `lead: 'en'`. */
  th?: string;
  /**
   * English leads and the Thai line is dropped. The commercial and deployment
   * sections only: PITCH_DECK §0 puts them in English because that is the
   * language hospital IT and procurement read contracts in. It has to be set
   * explicitly — an accidentally missing `th` is a bug, not a language choice.
   */
  lead?: 'en';
  /**
   * A second Thai line, set between the headline and the English. For a
   * headline that states a premise and then its consequence: the premise
   * carries the size, the consequence explains it, and the English stays
   * where it always is.
   */
  subTh?: string;
  en: string;
  /** A phrase of the leading language set apart in colour. Highlighted only
   *  when it occurs exactly once, so the wrong occurrence can never light up. */
  accent?: string;
  /** How the accent is set apart. Teal pulls the eye; muted lets it recede. */
  accentTone?: 'teal' | 'muted';
}

export type SlideId =
  | 'cover'
  | 'hook'
  | 'problems'
  | 'solution'
  | 'impact'
  | 'demo'
  | 'questions'
  /* The appendix — reference, after the ask. */
  | 'business'
  | 'pilot'
  | 'prep';

export interface SlideMeta {
  id: SlideId;
  section: SectionId;
  /**
   * A reference slide, parked after Questions rather than sitting in the run.
   * Steppable, deep-linkable and numbered like any other — but off the rail and
   * out of the notes total, because the room only reaches it by asking.
   * `budgetSec` stays authored: a presenter who does walk in here still needs to
   * know what it costs.
   */
  appendix?: boolean;
  /** Slide number as printed in PITCH_DECK. Cue cards have none. */
  number?: number;
  /** PITCH_DECK's budget in seconds. Drives the width of the rail segment. */
  budgetSec: number;
  presenter: Presenter;
  /** What the OTHER presenter does — §0's fourth column. */
  coPresenter?: string;
  /** Speaker notes, written in the presenter's own language. */
  notes: string[];
  /** Which repo doc this slide's content comes from. Shown in #/audit. */
  source?: string;
}

export interface ChecklistItem {
  /** `endpoint` sets the title in mono — it is an API call, not a heading. */
  kind?: 'bullet' | 'endpoint';
  title: string;
  body?: string;
  /** Named terms with a plain gloss each, for items whose substance IS the
   *  vocabulary — hospital IT has to recognise the term to answer, and
   *  everyone else needs it said in ordinary words. */
  terms?: { term: string; gloss: string }[];
  /** Says plainly that something is not built yet. Never soften this away —
   *  an over-claim here surfaces in week one of the pilot. */
  badge?: string;
  /** A nested spec breakdown, e.g. the VRAM budget under the GPU item. */
  rows?: { label: string; name: string; value: string; total?: boolean }[];
}

export interface ChecklistColumn {
  title: string;
  items: ChecklistItem[];
}

/** One union member per layout. Adding a layout is a compile-time event. */
export type Slide =
  /* The cover is a brand lockup, not a headline slide: it typesets the
     wordmark rather than the Thai/English pair. `headline` stays on it as the
     label the overview grid and the notes panel show. */
  | (SlideMeta & {
      layout: 'cover';
      headline: Headline;
      wordmark: { name: string; accent: string; product: string };
      tagline: string;
      team: { label: string; name: string };
    })
  | (SlideMeta & {
      layout: 'hero';
      headline: Headline;
      /** Numbers come from facts.ts; the labels beside them are copy. */
      stats: {
        total: { fact: FactKey; label: string };
        split: [{ fact: FactKey; label: string }, { fact: FactKey; label: string }];
        hero: { fact: FactKey; label: string; sub: string };
        source: string;
      };
    })
  | (SlideMeta & {
      layout: 'problems';
      eyebrow: { th: string; en: string };
      headline: Headline;
      items: { th: string; en: string }[];
    })
  | (SlideMeta & {
      layout: 'impact';
      eyebrow: { th: string; en: string };
      headline: Headline;
      /* 50% and 220 are deployment TARGETS, not measurements — which is why
         they are copy here rather than entries in facts.ts (real, sourced) or
         fills.ts (missing, chipped). Their caveats travel with them. */
      card: {
        label: string;
        prefix: string;
        figure: string;
        th: string;
        en: string;
        secondary: { figure: string; th: string; en: string };
      };
      /** Numbered 01, 02, … from position; only the label is authored. */
      items: { label: string; th: string; en: string }[];
      flow: { label: string; strong?: boolean }[];
      footer: { claim: string; caveat: string };
    })
  | (SlideMeta & {
      layout: 'solution';
      /** The MALI lockup that fills the left column. */
      brand: { name: string; accent: string; th: string; en: string };
      eyebrow: { th: string; en: string };
      headline: Headline;
      /** Numbered 01, 02, … from position; the number is not authored. */
      items: { th: string; en: string }[];
    })
  | (SlideMeta & {
      layout: 'business';
      eyebrow: { en: string };
      headline: Headline;
      subtitle: string;
      /** The aside that heads off the "do you build hardware?" question. */
      note: { title: string; body: string };
      /* Prices are quotes we authored, not measurements — so they are copy
         here, and the footer caveat that qualifies them is copy too. */
      tiers: {
        label: string;
        title: string;
        price: { figure: string; unit: string }[];
        lines: string[];
        muted: string;
        badge?: string;
      }[];
      businessCase: {
        label: string;
        title: string;
        muted: string;
        stats: { figure: string; label: string; muted?: string; tone?: 'teal' | 'ink' }[];
        payback: { label: string; rows: { share: string; months: string }[] };
      };
      caveat: string;
    })
  | (SlideMeta & {
      layout: 'checklist';
      eyebrow: { en: string };
      headline: Headline;
      columns: [ChecklistColumn, ChecklistColumn, ChecklistColumn];
      footer: string;
    })
  | (SlideMeta & {
      layout: 'pilot';
      eyebrow: { en: string };
      headline: Headline;
      lead: string;
      /* Every row is measured on both sides. The repetition is the argument —
         nothing here is cherry-picked after the fact. */
      table: {
        columns: [string, string, string];
        rows: { kpi: string; before: string; during: string }[];
      };
      outcome: { label: string; title: string; body: string };
    })
  | (SlideMeta & {
      /* A hold screen: the slides stop here and something else happens — the
         live demo, or questions. A light teal wash is what that means in this
         deck, so both are the same object and stay siblings by construction. */
      layout: 'hold';
      /* Not rendered on the slide — the grid and the notes panel read it. */
      headline: Headline;
      /* A plain word, or the cover's wordmark shape where the label should be
         typeset like the MALI lockup — one letter carrying the teal accent. */
      label: string | { lead: string; accent: string; tail: string };
      sub: string;
      /** Present only where the mark belongs; the demo screen carries none. */
      mark?: { size: number; motion?: MarkMotion; acts?: ShowreelAct[] };
      /** A small corner sign-off. The cover carries the full lockup; this is
       *  its footnote, for the screen that stays up through Q&A. */
      team?: { label: string; name: string };
    });
