# design-sync notes — AI-OPD kiosk frontend

- This is an APP repo, not a component library: no `dist/`, no `.d.ts` exports, `private: true`. The converter runs in synth-entry mode — `cfg.entry` deliberately points at a nonexistent `dist/index.js` so the package dir resolves via walk-up while entry resolution soft-fails into synthesis from `src/`.
- Two lib forks (declared in `cfg.libOverrides`):
  - `overrides/dts.mjs` — removed the `*Manager` suffix exclusion from `isComponentName`; `BpDeviceManager`/`CriteriaManager`/`DoctorScheduleManager` are real React components here.
  - `overrides/source-kit.mjs` — `NON_IMPL_RX` also excludes `main.tsx` (calls `createRoot` at module scope — with it bundled, the smoke check saw every export as non-component), `App.tsx`, and `src/pages/` (route screens, not DS components). Fork imports are repointed at `../../.ds-sync/lib/`; recreate `.design-sync/node_modules → ../.ds-sync/node_modules` symlink on fresh clones.
- CSS rides the JS module graph: `src/styles/ds-sync-styles.ts` (sync-owned file inside the app package, unused by the vite build) imports `global.css` + `kiosk.css`; it's wired via `cfg.extraEntries`. Do NOT use `cfg.cssEntry` here — both its branches (copy/append) leave `@import` statements unresolved.
- `cfg.extraEntries` also carries `src/i18n/index.ts` — its side effect initializes i18next (inline th/en resources, th default). Without it every component using `useTranslation` renders raw keys.
- Anuphan Variable ships as data-URI `@font-face` (from `@fontsource-variable/anuphan` via global.css) — no `fonts/` dir needed.
- `kiosk.css` is scoped under `.kiosk-root` (`.k-*` classes); previews of kiosk components that don't render their own kiosk-root wrapper need `<div className="kiosk-root">`.
- The api client (`src/api/client.ts`) reads `import.meta.env` — esbuild shims it to `{}` in the IIFE, so `baseUrl` falls back and admin panels render their "Failed to fetch" empty states in previews. That's the honest static state; not a defect.
- Playwright: chromium-headless-shell v1228 installed under `~/.cache/ms-playwright` with playwright in `.ds-sync/node_modules`.

## Known render warns
- `[TOKENS_MISSING] --border, --bg, --text-muted, --text, --color-text-muted, --color-bg-card, --color-general, --color-urgent` — pre-existing app CSS quirk: `global.css` references these with `var(..., fallback)` or relies on inheritance; they're never defined in the app either. Not a sync defect.
- `[FONT_MISSING] "Anuphan"` — appears only as a fallback family after "Anuphan Variable" in the font stacks; the primary family ships as data-URIs, so the fallback never resolves anywhere. Accepted.

## Re-sync risks
- `ds-sync-styles.ts` and the synth-entry exclusions must track `main.tsx`'s real imports — if the app adds a third global stylesheet or moves CSS imports, update `ds-sync-styles.ts`.
- New PascalCase exports under `src/pages/` are auto-excluded by the source-kit fork; new top-level screens elsewhere would need `componentSrcMap: null` entries.
- Admin-panel previews depend on their fetch-failure empty states staying styled; if the app adds error boundaries or loading spinners that never settle, those cards may change.
- The `.design-sync/overrides/*.mjs` forks shadow the staged lib — diff against `.ds-sync/lib/` after upgrading the skill and merge upstream changes.

## Preview-authoring gotchas (folded from wave learnings, 2026-07-24)
- `.kiosk-root` is `position: fixed; inset: 0` — every kiosk preview cell wraps in `<div className="kiosk-root" style={{position:'relative', inset:'auto', ...}}>` (or a `transform: translateZ(0)` containing block for fixed-position children like PatientIdPassPopup's modal).
- package-capture freezes the page clock → framer-motion elements screenshot at `initial` (opacity 0). Previews carry an in-cell style forcing `[style*="opacity"] { opacity: 1 !important }` / `[style*="transform:"] { transform: none !important }`. Applies to any future motion component preview.
- Headless capture had no Thai-capable input font AND kiosk.css doesn't set `font-family: var(--k-font)` on `input`/`textarea` (only root + button) — likely a REAL app bug on kiosk hardware without Thai system fonts; previews patch it locally. Suggest fixing kiosk.css.
- VoiceControls uses hardcoded emoji glyphs (🎤/🔊) — capture machine needed `~/.local/share/fonts/NotoColorEmoji.ttf` (user-level install, no sudo on this WSL). Re-install after OS resets.
- LanguageSwitcher default `variant="nav"` is white-on-transparent (for the gold header band) — invisible on white; previews use the `header` variant + a gold-band nav cell.
- Internal-state components (VisitIdCapture digits, HistoryIntakeStep fields, MeasurementCard deep flows) render their first/empty state only — that's the honest static render; interaction states are unreachable.
- KioskFrame cells render at 1280px+ with `zoom` to fit the capture viewport; if grid presentation ever degrades, the config-level alternative is `overrides.KioskFrame = {"cardMode":"single","viewport":"1400x900"}`.
