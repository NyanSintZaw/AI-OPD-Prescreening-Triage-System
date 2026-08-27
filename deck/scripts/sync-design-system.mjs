#!/usr/bin/env node
/**
 * Refresh src/design-system/ from the MALI package at the repo root.
 *
 * Same contract as hospital-hotline-assistant-web/scripts/sync-design-system.mjs:
 * the package is the source of truth, everything copied here is a byte copy,
 * and a forgotten copy ships a deck drawing itself with brand parts the product
 * no longer has. `--check` fails instead, and `npm run build` gates on it —
 * the deck is built rarely, and the night before a pitch is exactly when you
 * want to hear about drift.
 *
 *   node scripts/sync-design-system.mjs           copy
 *   node scripts/sync-design-system.mjs --check   report drift, exit 1
 *
 * src/design-system/index.css is deck-authored glue and is deliberately not
 * overwritten. Unlike the web app, the deck also vendors the fonts: a projector
 * laptop should need nothing but this repo.
 */
import { readFileSync, writeFileSync, readdirSync, mkdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const deck = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const pkg = resolve(deck, '../mali-design-system/src');
const dest = join(deck, 'src/design-system');

const files = [
  ...readdirSync(join(pkg, 'tokens'))
    .filter((f) => f.endsWith('.css'))
    .map((f) => [`tokens/${f}`, `tokens/${f}`]),
  // The deck has no global.css of its own, so unlike the web app it takes the
  // package's base layer too — the h1/h2/p resets under .mali-root.
  ['base.css', 'base.css'],
  ['components/Mark.tsx', 'components/Mark.tsx'],
  ['components/NongMali.tsx', 'components/NongMali.tsx'],
  ['motion.ts', 'motion.ts'],
  // Renamed on the way in: index.css imports it under this name.
  ['components/components.css', 'mali-components.css'],
  // Fonts — see the header note.
  ['fonts/anuphan.css', 'fonts/anuphan.css'],
  ...readdirSync(join(pkg, 'fonts/files'))
    .filter((f) => f.endsWith('.woff2'))
    .map((f) => [`fonts/files/${f}`, `fonts/files/${f}`]),
];

const check = process.argv.includes('--check');
const stale = [];

for (const [from, to] of files) {
  const src = readFileSync(join(pkg, from));
  const target = join(dest, to);
  let current = null;
  try {
    current = readFileSync(target);
  } catch {
    /* not vendored yet */
  }
  if (current && current.equals(src)) continue;
  stale.push(to);
  if (!check) {
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, src);
  }
}

if (!stale.length) {
  console.log(`design system in sync (${files.length} files)`);
} else if (check) {
  console.error(`design system is STALE — run npm run sync:ds\n  ${stale.join('\n  ')}`);
  process.exit(1);
} else {
  console.log(`synced ${stale.length}/${files.length}:\n  ${stale.join('\n  ')}`);
}
