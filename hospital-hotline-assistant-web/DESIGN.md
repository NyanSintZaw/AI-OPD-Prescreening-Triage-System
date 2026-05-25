# MFU Medical Center Design System

Visual styling for the hotline frontend is aligned with the [MFU Medical Center Hospital website](https://website01.mch.mfu.ac.th/en/mch-index.html).

## Brand colors

| Token | Hex | Usage |
|-------|-----|--------|
| `--mch-gold` | `#BA9643` | Navigation bar, accents, table headers |
| `--mch-gold-dark` | `#705A28` | Nav hover, active language pill |
| `--mch-cyan` | `#3EA3CB` | Primary buttons, footer, links |
| `--mch-cyan-light` | `#65B5D5` | Link hover, focus rings |
| `--mch-navy` | `#213253` | Button hover, headings accent |
| `--mch-red` | `#D63933` | Emergency alerts, section accents |
| `--color-bg` | `#F8F5F1` | Page background |
| `--color-bg-alt` | `#F2F1EB` | Cards, assistant bubbles |

Defined in [`src/styles/tokens.css`](src/styles/tokens.css).

## Typography

- **Headings:** Pridi (matches MFU MCH site)
- **Body:** Athiti (matches MFU MCH site)

Loaded via Google Fonts in `index.html`.

## Layout patterns

- **Header:** White logo band + gold navigation strip (like MFU MCH `header-menu-bar`)
- **Footer:** Cyan background (`#3EA3CB`) with white text
- **Buttons:** 5px radius, cyan primary with navy hover (service-box pattern)
- **Section titles:** Gold bottom border or red left accent (`head-line2` / `head-line4`)
- **Cards:** Warm off-white surfaces with soft shadow (`block3d` style)

## Logo & favicon

Official assets are loaded from the MFU MCH CDN:

- Logo: `Header_MCH_MFU_Thai.png`
- Favicon: `favicon-32x32.png`

To use local copies instead, place files in `public/` and update `Layout.tsx` and `index.html`.

## Customization

Edit `src/styles/tokens.css` to adjust the palette. Component styles in `src/styles/global.css` reference these tokens only — no hard-coded brand colors outside tokens.
