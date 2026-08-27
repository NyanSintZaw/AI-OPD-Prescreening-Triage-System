import { useEffect } from 'react';

export type Binding = { keys: string[]; run: () => void };

/**
 * One window-level key handler for the whole deck.
 *
 * PageUp and PageDown are bound because that is what a wireless presenter
 * remote sends — a deck that only listens for arrows is a deck you have to
 * stand at the laptop for. Escape is deliberately reserved for "close the
 * current overlay" and nothing else, so a stray press during the pitch can
 * never move the slide.
 */
export function useKeyboard(bindings: Binding[], enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const target = e.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;

      for (const b of bindings) {
        if (b.keys.includes(e.key)) {
          e.preventDefault();
          b.run();
          return;
        }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [bindings, enabled]);
}
