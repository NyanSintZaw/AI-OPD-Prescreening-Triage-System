# MALI Design System

**Single source of truth: the `mali-design-system/` package at the repo root**, authored in Claude Design (project `642c7d33-c1bc-48e3-a4b0-83d80f54441a`). It lives in this repo so the design system is versioned with the code that consumes it. The app *vendors* a subset — tokens, component CSS, the two brand marks, `motion.ts` — into `src/design-system/`, because it only uses a fraction of the package and must build without reaching outside its own directory.

**Edit the package, then `npm run sync:ds`.** Never hand-edit `src/design-system/`; those edits are lost on the next sync. `npm run sync:ds -- --check` fails if the copy has drifted — the app running motion code the package no longer has is exactly the bug it catches.

The earlier MFU/MCH website theme (gold `#BA9643`, cyan `#3EA3CB`, Pridi/Athiti webfonts, CDN logo) is **retired**. It is not a fallback and not a variant.

## Identity — Brand v1.0

| Mark | Component | Use |
|---|---|---|
| **Nong Mali** — the jasmine mascot | `NongMali` | The product's **main logo**. Headers, lockups, welcome screens, anywhere MALI speaks as a character. Greets once per session (`.mali-nong--bloom`), never looping decoration. 80px and up. |
| **The bud** | `Mark` | Loading and progress **only**: the conversation orb, step completion (`stage={0\|1\|3}` stamens), spinners, favicon, anything under 40px. |
| **Wordmark** | `Wordmark` | Anuphan Bold, teal `L` (Thai: teal `ล`). Carries Nong Mali by default; `mark="bud"` for dense headers; `tone="dark"` on deep-teal surfaces (paper letters, gold accent, gold signature bud); `friendly` for the lowercase gold i-dot cut. |

Masters: `mali-design-system/brand/` at the repo root (`nong-mali.svg`, `bud.svg`). Never recolour, stretch, rotate, or outline the marks. Keep clear space of half the mark's width.

## Colour

Every colour derives from the mark. Product code uses the **semantic layer only** — never a raw ramp step, never a hex.

| Role | Token | Value |
|---|---|---|
| Primary action | `--color-primary` | Mali Teal `#58A19D` (the logo colour); hover `--color-primary-hover` `#46867F` |
| Headings | `--text-heading` | Deep Leaf Ink `#1F3B38` |
| Signature accent | `--color-accent` | Stamen Gold `#DBB566` — **signal only**: active step, listening dot, wordmark i-dot, Orb speaking halo. Never a button fill, never a surface, never a large area. |
| Page surface | `--surface-page` | Paper `#FAF9F5` |
| Soft surface | `--petal` | Petal Cream `#DDE8DF` |
| Status | `--status-success/info/warning/danger` | `#3F8F6B` · `#4A7FB5` · `#B98F3E` · `#C05B4D` |
| Triage (MOPH 5-level) | `--triage-1…5` | Nurse and admin surfaces **only** |

**Patients never see a triage level, triage colour, diagnosis, or prescription.** Emergency red survives only where it means emergency.

Ramps (`--teal-*`, `--ink-*`, `--gold-*`) exist for the system's own use in `src/design-system/tokens/colors.css`.

## Typography

**Anuphan Variable only**, self-hosted (`@fontsource-variable/anuphan`) so the kiosk renders identically offline. It carries Thai and Latin in one voice — never add a second face. Scale: `--text-xs … --text-6xl`, plus `--text-kiosk-body` (22px), `--text-kiosk-question` (40px), `--text-kiosk-display` (56px). Thai is the default language and runs ~20% longer than English; check every layout with Thai strings.

## Shape, depth, motion

Radii `--radius-sm/md/lg/xl/full`. Shadows `--shadow-xs/sm/md/lg`, tinted with Deep Leaf Ink, never black; `--shadow-gold-halo` is the Orb speaking state alone. Motion tokens in `tokens/effects.css`: press `scale(.97)` at `--dur-press` 140ms, `--dur-color` 160ms, `--dur-exit` 200ms, `--dur-enter` 300ms, with `--ease-enter/exit/press`. Never `transition: all`; animate `transform` and `opacity` only; gate hover behind `@media (hover: hover) and (pointer: fine)`; every animation needs a `prefers-reduced-motion` companion.

**No gradients** (the Orb halo token is the sole exception), no glass/blur, no icon-card grids, no decorative icons, one accent per screen.

## Background texture

`.mali-texture-petals` (jasmine outlines + gold dots) and `.mali-texture-dots` appear **only on sparse screens** — welcome, waiting, loading, empty states. Never behind a question, a form, or a table body. If you notice it, it is too strong. The pattern never animates.

## Surfaces

- **Kiosk** (1080×1920 portrait, touch): paper canvas, one question on screen, `--hit-target-kiosk` 64px minimum. Nong Mali greets; the bud carries progress; only the Orb moves.
- **Nurse / admin portals** (1440 wide): dense tables over card lists, `--hit-target` 44px, triage badge colour is the only colour that carries meaning.

Full guidance ships with the package: `docs/guides/motion.md`, `docs/guides/craft.md`, and a per-component doc for each of the 19 components.

## One vocabulary

There is no alias layer. The retired `--mch-*` / `--color-*` names were swept out of the
codebase (commit following `f253cbb`) and `aliases.css` deleted — every rule now names a
MALI token directly. App layout constants (`--header-nav-height`, `--content-max-width`,
…) live in `src/styles/tokens.css`; they are app state, not design tokens.
