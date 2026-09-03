# design-sync notes — @notuning/mali-ds

- Package shape, no storybook. Build: `npm run build` (tsup → dist/index.js + index.d.ts; esbuild → dist/styles.css + dist/fonts/*.woff2).
- Converter entry: `--entry ./dist/index.js --node-modules ./node_modules`.
- Playwright is NOT a repo dep: the global install under `~/.nvm/versions/node/v24.19.0/lib/node_modules/playwright` is symlinked into `.ds-sync/node_modules/playwright` (recreate after re-staging `.ds-sync/`). Chromium cache: `chromium-1234`.
- Font stack must not list bare `'Anuphan'` — only `'Anuphan Variable'` ships, the bare name fired `[FONT_MISSING]`.
- Groups come from `docs/<Name>.md` frontmatter `category:` (Brand, Actions, Forms, Display, Feedback, Kiosk). Add a doc for every new component.
- `cfg.overrides`: column cardMode for wide stories; Modal is `single` with viewport 680x440 (its preview scopes `.mali-modal__backdrop{position:absolute}` inside a 640×400 frame).
- Previews wrap everything in `<div className="mali-root">` — the DS is opt-in via that class / `data-mali`.

- **Motion cards live on `Mark` and `NongMali`, not a `Motion` component.** The component list comes from the bundle's PascalCase exports, so a `previews/Motion.tsx` is dropped with `(stale preview: Motion — component no longer exported)`. `docs/Motion.md` still ships as a guideline (`guidelinesGlob` picks up `docs/*.md`) — the prose was never the gap, the visuals were.
- Motion tiles call `playMark(el, m, { force: true })` and replay one-shots on an interval; the attract loops and `nongRiseSway` self-repeat, so they pass `every={0}`. Without `force` a reduced-motion capture environment renders a still mark.
- `playMark`'s stage is the mark's PARENT element — attract rings/petals are DOM nodes, not SVG. Give each tile its own `position: relative; overflow: hidden` box or a lobby-scale ring draws across the neighbouring caption.
- A story row fits **4 tiles**; five overflow the card and the last one clips. `nongShowreel` therefore has its own `Showreel` cell. `cfg.overrides.NongMali.cardMode = column` for the extra width.

## Known render warns
- none.

## Re-sync risks
- Thinking/Orb stories animate; captures are a random frame — not a regression if the bead/orbit position differs.
- The app vendors a subset of this package into `hospital-hotline-assistant-web/src/design-system/` via `npm run sync:ds` (`-- --check` fails on drift). `src/tokens/*` stays the single source; a token edit here needs that sync before the app sees it. Preview/config-only changes (this run) need no sync.
- Motion cell captures are a random frame BY DESIGN (they force-play on mount). `budHand` regularly lands near-empty mid-sketch and `nongExplode` mid-fly-apart — neither is a regression. Judge those cells live in `.review.html`, not from the sheet.
- A new motion added to `MARK_MOTIONS` captions itself in the tiles but does NOT get a tile — add it to the right story in `previews/Mark.tsx` or `previews/NongMali.tsx` by hand.
