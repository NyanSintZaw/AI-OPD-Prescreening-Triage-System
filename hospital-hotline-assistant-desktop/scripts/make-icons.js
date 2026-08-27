/**
 * Generates assets/icon.png (512px, installer + app) and assets/tray.png (32px)
 * from code. `nativeImage` cannot read SVG, so the web app's favicon.svg is no
 * use here — and generating means no binary blobs in git and no manual step
 * before a build. Runs automatically via the prestart/predist npm hooks.
 */
const zlib = require('node:zlib');
const fs = require('node:fs');
const path = require('node:path');

// ─── minimal PNG writer (RGBA, no filtering) ───────────────────────────────

const CRC_TABLE = (() => {
  const table = new Int32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c;
  }
  return table;
})();

function crc32(buf) {
  let c = ~0;
  for (const byte of buf) c = CRC_TABLE[(c ^ byte) & 0xff] ^ (c >>> 8);
  return ~c >>> 0;
}

function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([length, body, crc]);
}

function encodePng(size, sample) {
  const raw = Buffer.alloc(size * (size * 4 + 1));
  let offset = 0;
  for (let y = 0; y < size; y += 1) {
    raw[offset++] = 0; // filter type: none
    for (let x = 0; x < size; x += 1) {
      const [r, g, b, a] = sample(x, y);
      raw[offset++] = r;
      raw[offset++] = g;
      raw[offset++] = b;
      raw[offset++] = a;
    }
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // colour type: RGBA
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk('IHDR', ihdr),
    chunk('IDAT', zlib.deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

// ─── the artwork: Mali Teal rounded square + white clipboard ───────────────

const TEAL = [70, 134, 127]; // --color-primary-hover, teal-600
const WHITE = [255, 255, 255];

/** Rounded-rect hit test in 0..1 space. */
function inRound(u, v, x0, y0, x1, y1, r) {
  if (u < x0 || u > x1 || v < y0 || v > y1) return false;
  const cx = Math.min(Math.max(u, x0 + r), x1 - r);
  const cy = Math.min(Math.max(v, y0 + r), y1 - r);
  return (u - cx) ** 2 + (v - cy) ** 2 <= r * r;
}

function colourAt(u, v, detail) {
  if (!inRound(u, v, 0.02, 0.02, 0.98, 0.98, 0.2)) return [0, 0, 0, 0];
  // clipboard body + the clip tab above it
  const body = inRound(u, v, 0.27, 0.22, 0.73, 0.82, 0.07);
  const clip = inRound(u, v, 0.4, 0.13, 0.6, 0.28, 0.04);
  if (clip) return [...WHITE, 255];
  if (body) {
    // three ruled lines, dropped on the tray icon where they would just blur
    const line = detail && u > 0.36 && u < 0.64
      && [0.4, 0.52, 0.64].some((y) => Math.abs(v - y) < 0.028);
    return line ? [...TEAL, 255] : [...WHITE, 255];
  }
  return [...TEAL, 255];
}

/** 3×3 supersample so the curves do not stair-step at 32px. */
function makeSampler(size, detail) {
  return (x, y) => {
    let r = 0;
    let g = 0;
    let b = 0;
    let a = 0;
    for (let sy = 0; sy < 3; sy += 1) {
      for (let sx = 0; sx < 3; sx += 1) {
        const [cr, cg, cb, ca] = colourAt((x + (sx + 0.5) / 3) / size, (y + (sy + 0.5) / 3) / size, detail);
        r += cr * ca;
        g += cg * ca;
        b += cb * ca;
        a += ca;
      }
    }
    // premultiplied average, then un-premultiply — keeps edges from darkening
    return a === 0 ? [0, 0, 0, 0] : [Math.round(r / a), Math.round(g / a), Math.round(b / a), Math.round(a / 9)];
  };
}

const assets = path.join(__dirname, '..', 'assets');
fs.mkdirSync(assets, { recursive: true });
for (const [name, size, detail] of [['icon.png', 512, true], ['tray.png', 32, false]]) {
  fs.writeFileSync(path.join(assets, name), encodePng(size, makeSampler(size, detail)));
}
console.log('icons written to assets/');
