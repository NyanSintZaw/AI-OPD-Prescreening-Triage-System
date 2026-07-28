# Kiosk Avatar — Frame Generation Guide

The kiosk avatar is now **frame-based**: it plays your actual character
pictures as animation loops (`SpriteAvatar.tsx`). You generate the frames
with your AI image tool, drop them in a folder, run one script, and the
kiosk animates them. Nothing is redrawn in code — what you generate is
exactly what patients see.

## Workflow

1. Generate the frames below with your image tool.
2. Save them as PNG into **`hospital-hotline-assistant-web/avatar-raw/`**
   named exactly **`<state>_<n>.png`** (e.g. `write_3.png`, `talk_open_1.png`).
3. From `hospital-hotline-assistant-web/` run:
   ```
   uv run --with pillow python scripts/process_avatar_frames.py
   ```
   This removes the background, aligns/scales every frame identically
   (anti-jitter), converts to webp, and writes `public/avatar/manifest.json`.
4. Refresh the kiosk. Missing sets degrade gracefully (e.g. no `think`
   frames yet → the idle frames are used); until any frames exist the old
   code-drawn avatar shows.

## The golden rules (what makes it look good)

AI generators drift between images — the whole game is consistency:

- **Edit, don't regenerate.** Make ONE base image you love, then use your
  tool's image-EDIT mode for every variant: "same image, change only the
  mouth to open", "same image, eyes closed". Never re-prompt from scratch.
- **Same framing every time**: front-facing, waist-up, character fully in
  frame, same size in frame, same crop line at the waist.
- **Flat single-color background** (plain light gray works best). No
  gradients, no texture — the background is removed automatically and
  flat backgrounds remove cleanly.
- **No random extras**: no sparkles, floating hearts, lightbulbs or props
  that appear in one frame and vanish in the next (they flicker).
- Small motions between frames read better than big ones — a pen moving
  2 cm beats an arm teleporting.

## Shot list (~40 frames)

| Files | What changes between frames | Used for |
|---|---|---|
| `idle_1..4` | subtle breathing: shoulders/chest rise a touch | waiting |
| `blink_1..2` | idle pose, eyes closed | blinks |
| `write_1..6` | pen tip progresses across the clipboard, head slightly down | **listening — the signature "taking notes" loop** |
| `write_blink_1` | writing pose, eyes closed | blinks while writing |
| `think_1..4` | pen to chin, eyes up; tiny head tilt variations | AI processing |
| `talk_closed_1..2` | talking pose, mouth closed | lip sync (quiet) |
| `talk_mid_1..2` | SAME pose, mouth half open | lip sync (medium) |
| `talk_open_1..2` | SAME pose, mouth wide open (happy) | lip sync (loud) |
| `wave_1..4` | greeting wave | hello screen (future) |
| `celebrate_1..4` | wink + thumbs up | result screen (future) |
| `confused_1..2` | head scratch, worried brows | error screen (future) |

The **talk_\*** trio matters most: those three must be pixel-identical
except the mouth (strict edit-mode variants of one base image). The
engine switches between them from the live loudness of the assistant's
voice — that's the lip sync.

Minimum viable set if you want to start small: `idle_1..2`, `blink_1`,
`write_1..3`, `think_1..2`, `talk_closed_1`, `talk_mid_1`, `talk_open_1`
(11 images) — everything else can be added later by just re-running the
script.
