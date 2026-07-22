"""Process raw avatar frames into web-ready sprite assets.

Usage (from hospital-hotline-assistant-web/):

    uv run --with pillow python scripts/process_avatar_frames.py
    uv run --with pillow python scripts/process_avatar_frames.py --selftest

Reads  avatar-raw/<state>_<n>.png   (flat near-uniform background)
Writes public/avatar/<state>_<n>.webp  +  public/avatar/manifest.json

Steps per frame:
  1. Background removal: flood fill alpha from the four corners with a
     color tolerance — works for flat AI-generated backgrounds; the
     character's dark outline stops the fill.
  2. Normalization (anti-jitter): find the content bounding box, scale so
     the character height is constant, center horizontally, bottom-align
     onto a fixed 660x880 canvas. Every frame lands in the same place.
  3. Export as WEBP quality 80.

Idempotent — re-run any time the raw folder changes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict, deque
from pathlib import Path

from PIL import Image

CANVAS_W, CANVAS_H = 660, 880
# Character occupies this fraction of canvas height after normalization.
FILL_RATIO = 0.96
BG_TOLERANCE = 28  # per-channel distance for the background flood fill
WEBP_QUALITY = 80

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "avatar-raw"
OUT_DIR = ROOT / "public" / "avatar"

# States the SpriteAvatar engine knows about. Extras are processed too,
# but these drive the "missing states" warning.
CORE_STATES = [
    "idle",
    "write",
    "think",
    "talk_closed",
    "talk_mid",
    "talk_open",
    "blink",
]

NAME_RE = re.compile(r"^([a-z][a-z0-9_]*?)_(\d+)$")


def remove_background(img: Image.Image) -> Image.Image:
    """Flood-fill transparent from the corners across near-uniform bg."""
    img = img.convert("RGBA")
    w, h = img.size
    px = img.load()

    # Sample the background color from the corners (majority wins).
    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    samples = [px[x, y][:3] for x, y in corners]
    bg = max(samples, key=samples.count)

    def is_bg(p) -> bool:
        return (
            abs(p[0] - bg[0]) <= BG_TOLERANCE
            and abs(p[1] - bg[1]) <= BG_TOLERANCE
            and abs(p[2] - bg[2]) <= BG_TOLERANCE
        )

    seen = bytearray(w * h)
    queue: deque[tuple[int, int]] = deque()
    for x, y in corners:
        if is_bg(px[x, y]):
            queue.append((x, y))
            seen[y * w + x] = 1

    while queue:
        x, y = queue.popleft()
        px[x, y] = (0, 0, 0, 0)
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx]:
                if is_bg(px[nx, ny]):
                    seen[ny * w + nx] = 1
                    queue.append((nx, ny))
    return img


def normalize(img: Image.Image) -> Image.Image:
    """Scale + position the character identically on every frame."""
    bbox = img.getbbox()  # bbox of non-transparent content
    if bbox is None:
        raise ValueError("frame is fully transparent after bg removal")
    content = img.crop(bbox)
    cw, ch = content.size

    target_h = int(CANVAS_H * FILL_RATIO)
    scale = target_h / ch
    content = content.resize((max(1, int(cw * scale)), target_h), Image.LANCZOS)

    canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    x = (CANVAS_W - content.width) // 2
    y = CANVAS_H - content.height  # bottom-aligned
    canvas.paste(content, (x, y), content)
    return canvas


def process_all() -> int:
    if not RAW_DIR.is_dir():
        print(f"No raw folder at {RAW_DIR} — create it and drop <state>_<n>.png files in.")
        return 1

    # NB: Windows globbing is case-insensitive — dedupe by resolved path
    # so *.png / *.PNG don't yield the same file twice.
    raw_files = sorted(
        {p.resolve() for p in list(RAW_DIR.glob("*.png")) + list(RAW_DIR.glob("*.PNG"))}
    )
    if not raw_files:
        print(f"No .png files found in {RAW_DIR}.")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    states: dict[str, list[str]] = defaultdict(list)
    errors = 0

    for path in raw_files:
        m = NAME_RE.match(path.stem.lower())
        if not m:
            print(f"  SKIP {path.name}: name must be <state>_<n>.png (e.g. write_3.png)")
            continue
        state, idx = m.group(1), int(m.group(2))
        out_name = f"{state}_{idx}.webp"
        try:
            img = Image.open(path)
            img = remove_background(img)
            img = normalize(img)
            img.save(OUT_DIR / out_name, "WEBP", quality=WEBP_QUALITY)
            states[state].append((idx, out_name))  # type: ignore[arg-type]
            print(f"  ok   {path.name} -> {out_name}")
        except Exception as exc:  # noqa: BLE001 - report and continue
            errors += 1
            print(f"  FAIL {path.name}: {exc}")

    manifest = {
        "canvas": [CANVAS_W, CANVAS_H],
        "states": {
            state: [name for _, name in sorted(frames)]
            for state, frames in sorted(states.items())
        },
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nWrote {OUT_DIR / 'manifest.json'} with {sum(len(v) for v in states.values())} frame(s).")

    missing = [s for s in CORE_STATES if s not in states]
    if missing:
        print(f"NOTE: no frames yet for: {', '.join(missing)} — the avatar engine will degrade gracefully.")
    return 1 if errors else 0


def selftest() -> int:
    """Generate synthetic raw frames, run the pipeline, verify output."""
    from PIL import ImageDraw

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    made = []
    for state, n, color in [("idle", 1, (200, 60, 60)), ("idle", 2, (60, 120, 200)), ("write", 1, (60, 160, 90))]:
        img = Image.new("RGB", (500, 700), (238, 238, 238))
        d = ImageDraw.Draw(img)
        # a vaguely character-shaped blob with a dark outline
        d.ellipse((150, 80, 350, 280), fill=color, outline=(40, 35, 30), width=8)
        d.rounded_rectangle((170, 280, 330, 620), 40, fill=color, outline=(40, 35, 30), width=8)
        p = RAW_DIR / f"selftest_{state}_{n}.png"  # prefixed name → skipped by NAME_RE? no: matches
        # keep the plain <state>_<n> convention so the pipeline picks it up
        p = RAW_DIR / f"{state}_{n}.png"
        img.save(p)
        made.append(p)

    code = process_all()

    ok = True
    manifest_path = OUT_DIR / "manifest.json"
    if not manifest_path.is_file():
        ok = False
    else:
        manifest = json.loads(manifest_path.read_text())
        got = manifest.get("states", {})
        ok = got.get("idle") == ["idle_1.webp", "idle_2.webp"] and got.get("write") == ["write_1.webp"]
        for f in got.get("idle", []) + got.get("write", []):
            out = OUT_DIR / f
            if not out.is_file():
                ok = False
            else:
                with Image.open(out) as check:
                    if check.size != (CANVAS_W, CANVAS_H):
                        ok = False

    # clean up synthetic inputs and outputs so a later real run starts fresh
    for p in made:
        p.unlink(missing_ok=True)
    for f in OUT_DIR.glob("*.webp"):
        f.unlink()
    manifest_path.unlink(missing_ok=True)

    print("\nSELFTEST " + ("PASSED" if ok and code == 0 else "FAILED"))
    return 0 if ok and code == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true", help="run the pipeline on synthetic frames")
    args = parser.parse_args()
    sys.exit(selftest() if args.selftest else process_all())
