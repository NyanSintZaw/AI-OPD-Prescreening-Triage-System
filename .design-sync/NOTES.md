# design-sync notes — @notuning/mali-ds

- Package shape, no storybook. Build: `npm run build` (tsup → dist/index.js + index.d.ts; esbuild → dist/styles.css + dist/fonts/*.woff2).
- Converter entry: `--entry ./dist/index.js --node-modules ./node_modules`.
- Playwright is NOT a repo dep: the global install under `~/.nvm/versions/node/v24.19.0/lib/node_modules/playwright` is symlinked into `.ds-sync/node_modules/playwright` (recreate after re-staging `.ds-sync/`). Chromium cache: `chromium-1234`.
- Font stack must not list bare `'Anuphan'` — only `'Anuphan Variable'` ships, the bare name fired `[FONT_MISSING]`.
- Groups come from `docs/<Name>.md` frontmatter `category:` (Brand, Actions, Forms, Display, Feedback, Kiosk). Add a doc for every new component.
- `cfg.overrides`: column cardMode for wide stories; Modal is `single` with viewport 680x440 (its preview scopes `.mali-modal__backdrop{position:absolute}` inside a 640×400 frame).
- Previews wrap everything in `<div className="mali-root">` — the DS is opt-in via that class / `data-mali`.

## Known render warns
- none.

## Re-sync risks
- Thinking/Orb stories animate; captures are a random frame — not a regression if the bead/orbit position differs.
- The app repo (`AI-OPD-Prescreening-Triage-System`) does not consume this package yet; when it does, keep `src/tokens/*` the single source.
