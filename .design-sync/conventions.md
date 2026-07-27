# MFU Kiosk Design System — conventions

This library is the UI of the MFU Medical Center AI pre-screening kiosk (patient-facing, Thai-first) plus its staff portals. It has **two styling worlds** — pick the right one before writing any markup:

## 1. Kiosk world (patient screens)

- Every kiosk-styled element must sit inside a `KioskFrame` (it renders the `.kiosk-root` scope itself) or, for a fragment, inside `<div className="kiosk-root">`. The `k-*` class rules exist globally, but all `--k-*` tokens they use are defined ON `.kiosk-root` — outside it the classes compute with missing values and the screen looks broken. Note `.kiosk-root` is a full-viewport fixed overlay; for an embedded fragment add `style={{ position: 'relative', inset: 'auto' }}`.
- Kiosk vocabulary: classes `k-btn`, `k-card`, `k-chip` for your own glue; tokens `var(--k-bg)`, `var(--k-border)`, `var(--k-border-strong)`, `var(--k-danger)`, `var(--k-danger-tint)`, `var(--k-font)`, font sizes `var(--k-fs-display)`, `var(--k-fs-title)`, `var(--k-fs-lead)`, `var(--k-fs-body)`, `var(--k-fs-body-lg)`, `var(--k-fs-caption)`, touch target `var(--k-touch)`, top bar height `var(--k-topbar-h)`.
- Kiosk UI is large-touch, one-decision-per-screen, no dense layouts.

## 2. Staff world (nurse/admin portals)

- Plain global CSS, no wrapper needed. Style layout glue with the brand tokens: `var(--mch-gold)`, `var(--mch-cyan)`, `var(--mch-navy)`, `var(--mch-red)`; semantic `var(--color-bg)`, `var(--color-surface)`, `var(--color-text)`, `var(--color-muted)`, `var(--color-border)`, `var(--color-primary)`, `var(--color-accent)`, `var(--color-emergency)`; fonts `var(--font-body)`, `var(--font-heading)`.

## Both worlds

- **No provider setup needed.** i18next is initialized inside the bundle (Thai default) — components self-translate; don't pass label text they already translate. The Anuphan Variable font ships embedded; never substitute another family.
- **Patient-safety rule baked into the components:** patient-facing surfaces (RecommendationCard, kiosk screens) never show triage level, color, or diagnosis — only the department and directions. Don't compose UI that adds severity labels next to them.
- Where the truth lives: `styles.css` → `_ds_bundle.css` (brand tokens at the top; the kiosk section is everything under `.kiosk-root`); per-component API in `components/<group>/<Name>/<Name>.d.ts` and usage in `<Name>.prompt.md`. Read those before inventing props.

## Idiomatic kiosk screen

```jsx
import { KioskFrame, AiOrb } from 'hospital-hotline-assistant-web';

<KioskFrame>
  <div style={{ display: 'grid', placeItems: 'center', gap: 24, padding: 32 }}>
    <AiOrb state="listening" />
    <p style={{ fontSize: 'var(--k-fs-lead)', fontFamily: 'var(--k-font)' }}>
      มีอาการอะไรให้ช่วยดูแลคะ
    </p>
    <div style={{ display: 'flex', gap: 12 }}>
      <button className="k-chip">ปวดหัว</button>
      <button className="k-chip">มีไข้</button>
    </div>
  </div>
</KioskFrame>
```
