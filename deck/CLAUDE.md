# deck/ — the pitch deck as a website

The two-presenter, Thai + English pitch from `PITCH_DECK.md`, rendered as an animated site
you present from a browser — six minutes on the rail, four of which are the live demo, then
Q&A, with three reference slides parked behind it. React 19 + Vite, same toolchain as
`hospital-hotline-assistant-web/`.

```bash
npm install
npm run dev                                   # http://localhost:5174
npm run build && npm run preview -- --host    # the projector path (a real origin)
npm run build:single                          # single-file dist/index.html, works over file://
```

Port 5174, never 5173 — the deck must not fight the kiosk it is about to demo.

## Five rules

1. **Never hand-edit `src/design-system/`.** It is a byte copy of `mali-design-system/src`.
   Edit the package, then `npm run sync:ds`. `index.css` in that folder is the one
   deck-authored file. `npm run build` runs `sync:ds --check` first and fails on drift,
   because a deck drawing itself with brand parts the product no longer has is the exact
   failure you cannot see from inside the deck.
2. **All copy lives in `src/content/slides.ts`.** Layouts are components and carry no
   strings. Numbers that are *missing* live in `fills.ts`; numbers that are *real* live in
   `facts.ts` with a mandatory `source`. They are separate files on purpose — they have
   opposite failure modes, and merging them lets a real number acquire a `[FILL]` chip's
   forgiveness.
3. **Thai leads, always.** Only `<SlideHeadline>` typesets a title — the sole exception is
   the cover, which is a brand lockup rather than a headline slide and sets the MALI
   wordmark itself; its `headline` stays in the data as the label the overview grid and the
   notes panel show. Everywhere else `Headline` has no field that reverses the order, so
   "English big" is not expressible. Never
   `--tracking-tight` on Thai (negative tracking collides tone marks with the next glyph);
   never Thai body text in `--text-muted` (4.9:1 survives a monitor and dies on a dim
   projector); never `--leading-tight` on Thai (it clips tone marks and lower vowels at
   display size — Thai leading is 1.4).
4. **Motion is variants + `staggerChildren`, never hand-tuned delays.** Transform and
   opacity only. Exits faster than enters. No framer-motion `layout` props anywhere — the
   stage is inside a `transform: scale()` and layout animations misbehave there.
5. **The design system supplies the palette. It does not supply the layout.** Slides are a
   pitch surface, not a product surface: radii, shadows, blur, spacing and type scale are
   set for a room and a projector, and are free to be bolder than the kiosk's. Colours stay
   on tokens so the deck and the product never disagree about what teal is.

## Two ways framer-motion will quietly break a layout

Both of these have already cost real debugging time here.

- **Spreading motion props next to `style` clobbers it.** `<motion.div style={{flexGrow}}
  {...grow()}>` where `grow()` returns its own `style` drops the `flexGrow` entirely. Helpers
  in this deck return only `initial`/`animate`/`transition`; anything visual goes in the one
  `style` object on the element.
- **A motion element's `transform` is written by framer, not by your CSS.** Centring with
  `transform: translateY(-50%)` on a `Block` silently stops working the moment its variants
  animate `y`. Position such elements with a plain `<div>`, or centre them without transform.

## Things that look like bugs and are not

- **The 420ms slide enter** exceeds the design system's 300ms ceiling. That ceiling governs
  a transition the user is waiting on after their own click; a slide change is a
  presentational beat read from eight metres, where 300ms reads as a snap. Deliberate.
- **The `EscalationGate` spring overshoots.** `docs/guides/motion.md` forbids bounce on
  *feedback*. That visual is a depiction of a clinical escalation, and the snap is what
  sells "immediately, mid-interview". Deliberate.
- **The deck runs a louder motion budget than the product.** The design system's motion
  guide restrains motion in the kiosk and the portals. A deck is a different surface; it
  reuses the same easing and duration tokens and spends them more freely.
- **Every heading class in this deck is scoped under `.deck-root`, and has to be.** The
  design system's base layer sizes `h1`/`h2`/`h3` at 24/20/18px for product UI, and those
  rules outrank a bare class — an unscoped slide heading silently renders as a caption. This
  has now caught `.d-th`, `.d-screen-title` and `.d-prep-col-title`. Write new ones as
  `.deck-root .d-your-heading`.
- **`.deck-root p { max-width: none }` in `deck.css` is load-bearing.** The same base layer
  caps every `<p>` at `--measure` (68ch) for readable product prose. On a 1920 stage that
  folds a full-width line into a half-width column without any error — it just looks like a
  layout you chose. Both of these are the same trap: the design system's *typography* is
  sized for a product, and slides are not a product.
- **The deck steps past Q&A into three more slides.** `business`, `pilot` and `prep` sit
  after `questions` on purpose: reference for the questions that need them, not part of the
  run. So `End` lands on Questions rather than on the last slide; the rail and the notes
  total read `PITCH_SLIDES` rather than `SLIDES`, which is what keeps the total at 6:00; and
  those three still carry real budgets of 1:00, 0:40 and 2:00, which the overview grid and
  the notes clock still show — a presenter who does walk in there needs to know the cost.
  `SLIDES` order is step order, and `appendix` is a timing/routing flag, deliberately not a
  `SectionId`: `prep` is still the deployment section whether or not you present it.
- **A fixed 1920-wide stage, not `clamp()`.** The kiosk uses `clamp()` because it runs on
  one known screen forever. A deck runs once on a projector nobody measured, and a fluid
  headline breaks in a different place there than in rehearsal. `useStageScale` scales a
  fixed canvas so what you rehearsed is what projects, Thai line breaks included. The
  canvas *height* does flex (up to 1.6x) so a 16:10 laptop or a 4:3 projector is filled by
  the deck's own paper instead of grey letterbox bars — line breaking is a function of
  width alone, and `.deck-slide` stays exactly 1080 tall and centred, so nothing moves.

## Keys

`→ ↓ Space PageDown` next · `← ↑ PageUp` previous · `Home` cover / `End` **Questions, not
the last slide** · `1`–`4` the pitch, `5`–`7` the appendix, `0` Questions · `O` overview ·
`N` presenter notes · `F` fullscreen · `T`/`R` timer · `B` or `.` blackout · `A` the `[FILL]`
register · `Q` Q&A · `V` measured quality · `M` force motion · `?` help.

`PageUp`/`PageDown` are bound because that is what a wireless presenter remote sends. On a
touchscreen, a horizontal swipe changes slide; vertical is left alone so the aside screens
still scroll.

## Screens off the pitch flow

`#/audit` the `[FILL]` register · `#/qa` the eight prepared questions · `#/quality` the
measured numbers with their caveats · `#/leavebehind` the one-page PDF (Ctrl+P, A4 portrait,
background graphics on) · `#/typecheck` every Thai string at its real size, for reading from
the back of the actual room.

## Before you present

- `#/audit` must show zero unfilled. PITCH_DECK §5: never present a visible `[FILL]` —
  either the number, or the sentence "to be measured in the pilot".
- Check `#/typecheck` on the actual projector. Thai tone marks are the first thing to
  disappear at low contrast, and they disappear at projector scale, not at 100% in a browser.
- If the machine has reduced motion on (Windows → Accessibility → Visual effects), the deck
  flattens itself and says so on the cover. Press `M`.
- Three verify-before-you-say-it items are marked in the content with comments: the
  VN→HN identity change on the deployment prep slide (`src/content/prep.ts`), the
  per-pathway BP card in cue A, and which patient actually fires the emergency in cue B.
  Run the demo and confirm. (The file, not a slide number — for the same reason this deck
  routes on slugs rather than indices.)
