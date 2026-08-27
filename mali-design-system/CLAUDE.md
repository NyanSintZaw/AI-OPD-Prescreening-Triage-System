# MALI design system (`@notuning/mali-ds`)

- **This is the source of truth for the brand.** Authored in Claude Design (project `642c7d33-c1bc-48e3-a4b0-83d80f54441a`, config in `.design-sync/`) and edited here — never in the app's vendored copy at `hospital-hotline-assistant-web/src/design-system/`, whose files are byte copies that the next sync overwrites.
- After changing anything the app uses (`src/tokens/*`, `src/components/Mark.tsx`, `src/components/NongMali.tsx`, `src/components/components.css`, `src/motion.ts`), run `npm run sync:ds` from `hospital-hotline-assistant-web/`. `npm run sync:ds -- --check` fails on drift.
- Build: `npm run build` (tsup → `dist/`, gitignored). `dist/` and `ds-bundle/` are output, never committed.
- `src/motion.ts` holds every logo motion (`playMark(host, motion)`): bud loaders (`budDraw`, `budFilled`, `budHand`, `budGrow`) and Nong Mali's entrances and attract loops (`nongRise`, `nongWave`, `nongBloom`, `nongRiseSway`, `nongExplode`, `nongHeartbeat`, `nongWaveHello`, `nongBounce`, `nongShowreel`). `MARK_MOTIONS` / `ATTRACT_MOTIONS` list them with their roles. Docs in `docs/Motion.md`.
- **Nong Mali is the product's main logo; the bud is for loading/progress only.**
- Brand masters in `brand/` (`nong-mali.svg`, `bud.svg`, `brand-guidelines.html`). Anuphan is self-hosted in `src/fonts/` — the kiosk runs offline.
