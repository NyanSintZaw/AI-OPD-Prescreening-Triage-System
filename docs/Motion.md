---
category: Brand
---
The seven approved logo motions, ported from the Brand Guidelines canvas. Pass the `motion` prop to `<Mark>` or `<NongMali>` to play one on mount, or call `playMark(element, name)` to trigger one yourself. Every call resets the mark first, so replaying mid-flight is safe, and each returns a handle with `cancel()`.

**Nong Mali** — greeting moments, once per session, never looping decoration:
`nongBloom` (welcome — every part springs open in turn, then she settles into a slow sway that keeps running), `nongRise` (quiet entrance — parts glide up in sequence), `nongWave` (greeting — she pops in and waves).

**The bud** — work and progress:
`budDraw` (loading — each outline draws itself, then its fill arrives and the stamen dots pop), `budFilled` (reveal — shapes wipe upward in turn), `budHand` (signature sketch — the silhouette splits into petals that wipe in from different directions, then the stamens draw and dot), `budGrow` (step complete — grows from its base with a small overshoot).

These are Web Animations API sequences over the SVG's own paths, not CSS keyframes: they measure paths with `getTotalLength()`, wipe with `clip-path`, and stagger per-path on a spring curve. They are skipped entirely under `prefers-reduced-motion` — the mark snaps to its resting state and nothing is scheduled — unless you pass `{ force: true }`.

`nongBloom` ends in an infinite sway; it is the only motion that does not finish. Reach for `nongRise` where a mark must come to rest.
