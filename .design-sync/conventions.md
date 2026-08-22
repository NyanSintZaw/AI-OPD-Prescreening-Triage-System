# MALI design system — how to build with it

MALI (Multilingual Assistant powered by Local Intelligence) is the no tuning team's clinical assistant; this system styles MALI Prescreening — a patient kiosk, a nurse review portal and an admin portal for MFU Medical Center. Thai is the default language; every string must also work in English. The look is quiet and warm: ink text on paper, hairlines, one gold signature. It must never look "AI-generated" — no gradients, no glass/blur, no glow except the Orb, no icon-card grids, no emoji.

## Setup

Wrap the app once in `<div className="mali-root">` (or put `data-mali` on the root element). Without it fonts, colours and focus rings are not applied. The stylesheet is `styles.css` (ships Anuphan Variable as self-hosted woff2 — do not link Google Fonts). No provider, no context, no JS theme object.

## Styling idiom: CSS custom properties

Components are styled; your own layout glue uses the tokens via `var(--*)`. Never hard-code hex or px that a token covers.

| Need | Tokens |
|---|---|
| Surfaces | `--surface-page` (paper), `--surface-card`, `--surface-muted`, `--surface-sunken` |
| Text | `--text-heading`, `--text-body`, `--text-muted`, `--text-subtle` |
| Borders | `--border-subtle`, `--border-default`, `--border-strong` |
| Action colour | `--color-primary` (ink-900; buttons are near-black), `--color-primary-hover`, `--color-primary-soft` |
| Gold signature | `--color-accent`, `--color-accent-soft`, `--focus-ring` — small accents only: active step, focus, a dot. Never a fill for buttons or large areas |
| Status | `--status-success/-info/-warning/-danger` (+ `-soft`) |
| Triage (nurse/admin ONLY) | `--triage-1 … --triage-5` (+ `-soft`). Never on kiosk surfaces; patients never see a level |
| Type | `--font-sans` (Anuphan), sizes `--text-xs … --text-6xl`, kiosk `--text-kiosk-body` 22px / `--text-kiosk-question` 40px, weights `--fw-regular/medium/semibold/bold`, `--tracking-label` for 11px uppercase labels (class `.mali-label`) |
| Space | 4px rhythm `--space-1 … --space-15`; `--pad-card` 20px, `--pad-page` 32px, `--gap-stack` 16px; hit targets `--hit-target` 44px, `--hit-target-kiosk` 64px |
| Shape & depth | `--radius-sm/md/lg/xl/full`; `--shadow-xs/sm/md/lg` (ink-tinted, never black), `--shadow-gold-halo` (Orb only) |
| Motion | `--ease-enter`, `--ease-exit`, `--ease-press`; `--dur-press` 140ms, `--dur-color` 160ms, `--dur-exit` 200ms, `--dur-enter` 300ms. Press = `scale(var(--press-scale))`. Never `transition: all`. Gate hover behind `@media (hover:hover) and (pointer:fine)`. Only the Orb animates on the kiosk |

## Surface rules

- **Kiosk** (patient-facing): one question per screen via `KioskQuestion`, `Orb` centred above it, answers as `Chip size="kiosk"` or `Button size="kiosk"`, `Stepper size="kiosk"` at the top, `Wordmark` once. No tables, no triage Badge, no level/colour words.
- **Nurse / Admin**: `DataTable density="compact"` for queues, `Badge level={n}` is the only colour on the page, `Card` for detail panes (never nested, never a grid of identical cards), `Field` + `Input/Select/Textarea` for forms, `Modal` only for escalation/destructive confirms, `Toast` bottom-right.
- Loading vs thinking: `Spinner` for data, `Thinking label="MALI is listening"` for AI work — never swap them.

## Where the truth lives

Read `styles.css` and its import `_ds_bundle.css` for every token and class; each `components/<group>/<Name>/<Name>.prompt.md` for usage rules; `<Name>.d.ts` for props.

## Idiomatic snippet

```jsx
<div className="mali-root" style={{ minHeight: '100vh', padding: 'var(--pad-page)' }}>
  <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-10)' }}>
    <Wordmark height={24} product="Prescreening" />
    <Badge tone="success">HIS synced</Badge>
  </header>
  <Card title="Review queue" aside={<Button size="sm" variant="secondary">Refresh</Button>} padding="none">
    <DataTable density="compact" rows={rows} rowKey={(r) => r.hn} onRowClick={open}
      columns={[{ key: 'hn', header: 'HN' }, { key: 'name', header: 'Patient' },
                { key: 'level', header: 'Triage', render: (r) => <Badge level={r.level} /> }]} />
  </Card>
</div>
```

## Before composing a screen
Read `guidelines/docs/guides/motion.md` (what moves, how fast, what never moves) and `guidelines/docs/guides/craft.md` (the reject list: one accent, no gradients/glass/icon grids, Thai-first type). They are short and non-negotiable.
