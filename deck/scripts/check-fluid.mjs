/**
 * Asserts that every selector in `src/styles/fluid.css` is scoped to
 * `.deck-root--fluid`.
 *
 * This is the whole safety story for fluid mode. The deck's reason to exist is
 * a projector, and the fixed 1920 stage is the decision that makes a rehearsed
 * Thai line break survive to the room (see `useStageScale.ts`). Fluid mode is
 * allowed to exist only because it cannot reach that: the projector never sets
 * the class, so a scoped rule can never apply there.
 *
 * "Every rule is scoped" is easy to believe and easy to break — one selector
 * pasted in without the prefix silently changes the stage, and you find out in
 * front of the room rather than here. So it is checked, in the same place and
 * the same idiom as `sync-design-system.mjs --check`.
 */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const FILE = join(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'styles', 'fluid.css');
const GATE = '.deck-root--fluid';

const css = readFileSync(FILE, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

const offenders = [];
let selectors = 0;

/* Everything before a `{` is a selector list. Declarations cannot contain a
   brace, so each match starts after the previous block's `}`. At-rules
   (@media, @supports) are containers, not selectors — their own contents get
   matched and checked on the next pass through the loop. */
for (const [, raw] of css.matchAll(/([^{}]+)\{/g)) {
  const list = raw.trim();
  if (!list || list.startsWith('@')) continue;

  for (const selector of list.split(',')) {
    const s = selector.trim();
    if (!s) continue;
    selectors += 1;
    if (!s.includes(GATE)) offenders.push(s);
  }
}

if (offenders.length > 0) {
  console.error(
    `\nfluid.css: ${offenders.length} selector(s) are not scoped to ${GATE}.\n` +
      `Unscoped rules in this file apply to the PROJECTOR, which is the one\n` +
      `thing fluid mode must never touch. Add the gate, or move the rule to\n` +
      `layouts.css if it genuinely belongs to both modes.\n`,
  );
  for (const s of offenders) console.error(`  ${s}`);
  console.error('');
  process.exit(1);
}

console.log(`fluid.css scoped (${selectors} selectors)`);
