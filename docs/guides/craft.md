---
category: Guides
---
# Craft floor

The baseline every MALI screen has to clear. These are the patterns that make interfaces read as generated rather than designed; none of them are allowed.

## Colour

- One accent per screen. Stamen Gold (`--color-accent`, #DBB566) is a signature: active step, listening dot, wordmark i-dot, Orb speaking halo — at most one small element. Never a button fill, never a background, never a large area.
- Primary actions are Mali Teal (`--color-primary`, #58A19D — the logo colour); hover is teal-600. Headings are Deep Leaf Ink #1F3B38. Hierarchy comes from weight and size, not from extra colours. Never more than three families (teal, gold, paper) on a kiosk screen.
- Text contrast ≥ 4.5:1 on its background. `--text-subtle` is for metadata only, never for body copy or labels that carry meaning.
- Triage colours (`--triage-1…5`) appear only in nurse/admin surfaces and only on a `Badge`. The kiosk never shows a level, colour, or diagnosis.
- No gradients. The only exception is the Orb speaking halo, which is a token (`--shadow-gold-halo`).
- Background texture (`.mali-texture-petals`, `.mali-texture-dots`) only on sparse screens — welcome, waiting, loading, empty states. Never behind a question, a form or a table body; if you notice it, it is too strong. The pattern never animates.
- No gradient text, no duotone, no colour-tinted backgrounds behind sections to "add interest".

## Surfaces and depth

- Depth is `--shadow-xs/sm/md` (offset + blur, ink-tinted) or a `--border-subtle` line. Not both on the same element.
- No glassmorphism, no `backdrop-filter`, no frosted panels, no blur for decoration.
- No coloured side borders wider than 1px. A `Toast` has its 2px tone bar on top; nothing else gets a stripe.
- Cards are for grouping a unit of content with a title. Not every paragraph needs a card. Not every list item needs a card.
- No icon-card grids ("three features with an icon each"). No icons as decoration at all; an icon appears only when it replaces a word the user would otherwise read.

## Typography

- One family: Anuphan Variable. Weights 400 / 500 / 600 / 700 only.
- Use the scale (`--text-xs` … `--text-6xl`, plus the `--text-kiosk-*` sizes). No ad-hoc font sizes.
- Eyebrows / micro-labels (`.mali-label`, 11px uppercase tracked) belong on at most one element per view, above a section title. Not on every card.
- Headings use `--tracking-tight` (−0.01em) at ≥ 30px. Body text is never letter-spaced.
- Thai is the default language; check every layout with Thai strings, which run ~20% longer and have taller ascenders. Line-height `--leading-normal` or looser for Thai body copy.
- Measure ≤ `--measure` (68ch). Never full-width paragraphs.

## Layout and spacing

- Use the `--space-*` rhythm. No `13px`, no `0.9rem`.
- Hit targets: 44px portal (`--hit-target`), 64px kiosk (`--hit-target-kiosk`).
- Kiosk is 1080×1920 portrait: one question on screen, `Orb` centred, transcript as quiet captions under it. No chat bubbles, no avatars-in-circles, no split panes.
- Portals are 1440 wide, dense: tables, not card lists, for queues. Filters in one row above the table.
- Empty states are one sentence and, when useful, one action. No illustrations.

## Copy

- Sentence case everywhere except `.mali-label`.
- Buttons are verbs: "Confirm", "Start", "Review". Never "OK", "Submit", "Click here".
- No exclamation marks, no emoji, no "✨", no "Welcome to…" hero copy.
- Patient-facing text never mentions triage levels, colours, urgency tiers, diagnoses, or medication. It says where to go and what happens next.

## Quick reject list

Gradient text · glass panels · icon-card trios · eyebrow on every card · hover-lift · shimmer skeletons · rounded-full everything · 3-column "feature" grids · decorative blobs · dotted backgrounds · emoji · placeholder lorem · mixed radii on one screen · more than one accent · centred long paragraphs.
