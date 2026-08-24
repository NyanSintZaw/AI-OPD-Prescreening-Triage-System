---
category: Guides
---
# Motion

Rules for anything that moves. Borrowed from Emil Kowalski's design-engineering practice; the tokens in `effects.css` already encode the numbers, so reach for the token, never a literal.

## Defaults

| Need | Token | Value |
|---|---|---|
| Button / chip press | `--dur-press` + `--ease-press` | 140ms, `scale(var(--press-scale))` = .97 |
| Colour, border, opacity | `--dur-color` | 160ms |
| Anything leaving | `--dur-exit` + `--ease-exit` | 200ms, ease-in (`cubic-bezier(.4,0,1,1)`) |
| Anything entering | `--dur-enter` + `--ease-enter` | 300ms, strong ease-out (`cubic-bezier(.16,1,.3,1)`) |
| Orb idle breathing | `--dur-breathe` | 2400ms, the only slow loop allowed |

- UI transitions stay under 300ms. Longer reads as lag, not elegance.
- Exits are faster than enters. The user already decided to leave; don't make them wait.
- Ease-out for things entering, ease-in for things leaving, ease-in-out only for things that move from A to B while staying on screen.
- Never `transition: all`. Name the property (`transform`, `opacity`, `background-color`).
- Animate `transform` and `opacity` only. No animated `height`, `width`, `top`, `box-shadow`.
- Hover states live behind `@media (hover: hover) and (pointer: fine)`. The kiosk is a touch screen; hover there is a bug.
- Every animation has a `prefers-reduced-motion: reduce` companion. The tokens already collapse durations to 0ms under it; keyframe loops (Orb, Thinking, Spinner) must still render a sensible static frame.

## What does NOT animate

- Kiosk: only the `Orb` moves in conversation (listening / thinking / speaking). Two approved brand entrances exist — `.mali-nong--bloom` (Nong Mali greets, once per session) and `.mali-mark--grow` (bud on step complete). Questions, captions, steppers and buttons appear in place. No slide-ins, no staggered reveals, no typewriter text.
- Nurse / admin portals: tables, cards, badges are static. Feedback (Toast, Modal) gets the one enter/exit; rows and filters do not.
- Nothing loops forever except `Orb`, `Thinking`, `Spinner`, and those only while real work is happening. Background textures never animate.
- No parallax, no scroll-driven effects, no hover-lift on cards, no shimmer skeletons. A `Spinner` or `Thinking` is the loading state.

## Feel

- Press feedback is the one animation every interactive element must have. `scale(.97)` in 140ms, release at the same speed.
- Feedback should confirm, not celebrate. No bounce, no overshoot, no confetti, no pulsing CTAs.
- If an animation exists only to look "alive", delete it.
