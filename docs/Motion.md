---
category: Brand
---
The seven approved logo motions, ported from the Brand Guidelines canvas. Pass the `motion` prop to `<Mark>` or `<NongMali>` to play one on mount, or call `playMark(element, name)` to trigger one yourself. Every call resets the mark first, so replaying mid-flight is safe, and each returns a handle with `cancel()`.

**Nong Mali** — greeting moments, once per session, never looping decoration:
`nongBloom` (welcome — every part springs open in turn, then she settles into a slow sway that keeps running), `nongRise` (quiet entrance — parts glide up in sequence), `nongWave` (greeting — she pops in and waves).

**The bud** — work and progress:
`budDraw` (loading — each outline draws itself, then its fill arrives and the stamen dots pop), `budFilled` (reveal — shapes wipe upward in turn), `budHand` (signature sketch — the silhouette splits into petals that wipe in from different directions, then the stamens draw and dot), `budGrow` (step complete — grows from its base with a small overshoot).

**Attract loops** — for the booth screen, bigger and more theatrical than the in-app set, and they run forever without a tap:
`nongWaveHello` (wave hello — she leans toward the patient and waves her side petal while bobbing, straightens, does a squash-and-stretch hop, then sways until she waves again; the most welcoming loop for greeting people at the booth), `nongShowreel` (the mixer — wave hello, heartbeat and rise-sway in a random order, with the repeat counts varied too, and never the same act twice in a row, so a passer-by never sees a fixed loop), `nongExplode` (fly apart & snap — she breaks into her parts, which drift outward and hover in an exploded view, bobbing gently, then snap back together with a ring burst and a petal splash), `nongHeartbeat` (heartbeat burst — a lub-dub double pulse every beat, each throwing off expanding rings and a scatter of jasmine petals; a medical rhythm made friendly).

These two also draw **outside** the SVG: expanding rings and petal particles are DOM nodes added to the mark's parent, so the parent wants to be roughly twice the mark's size and is temporarily made `position: relative` if it is `static` (restored on cancel). Pass `{ stage }` to draw them somewhere else. Everything spawned is removed when the handle is cancelled.

These are Web Animations API sequences over the SVG's own paths, not CSS keyframes: they measure paths with `getTotalLength()`, wipe with `clip-path`, and stagger per-path on a spring curve. They are skipped entirely under `prefers-reduced-motion` — the mark snaps to its resting state and nothing is scheduled — unless you pass `{ force: true }`.

`nongBloom` ends in an infinite sway; it is the only motion that does not finish. Reach for `nongRise` where a mark must come to rest.
