#!/usr/bin/env node
/**
 * Refresh src/design-system/ from the MALI package at the repo root.
 *
 * The app consumes a subset — tokens, the two brand marks, the motion
 * library, the component CSS — not the whole package, so this is a copy
 * rather than an import. Keeping the copy meant remembering to make it, and
 * a forgotten one ships an app running motion code the package no longer
 * has. `--check` fails instead, so CI or a pre-push hook can catch it.
 *
 *   node scripts/sync-design-system.mjs           copy
 *   node scripts/sync-design-system.mjs --check   report drift, exit 1
 *
 * src/design-system/index.css is app-authored glue (it pulls the app's own
 * subset together) and is deliberately not overwritten.
 */
import { readFileSync, writeFileSync, readdirSync, mkdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const web = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const pkg = resolve(web, '../mali-design-system/src');
const dest = join(web, 'src/design-system');

const files = [
  ...readdirSync(join(pkg, 'tokens'))
    .filter((f) => f.endsWith('.css'))
    .map((f) => [`tokens/${f}`, `tokens/${f}`]),
  ['components/Mark.tsx', 'components/Mark.tsx'],
  ['components/NongMali.tsx', 'components/NongMali.tsx'],
  ['motion.ts', 'motion.ts'],
  // Renamed on the way in: the app's index.css imports it under this name.
  ['components/components.css', 'mali-components.css'],
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
