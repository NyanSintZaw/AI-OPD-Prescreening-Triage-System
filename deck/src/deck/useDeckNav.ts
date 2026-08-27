import { useCallback, useEffect, useState } from 'react';
import { SLIDES } from '../content/slides';
import type { SlideId } from '../content/types';

/** Screens that live outside the pitch flow and off the timing rail. */
export const ASIDE_ROUTES = ['qa', 'audit', 'quality', 'leavebehind', 'notes-print', 'typecheck'] as const;
export type AsideRoute = (typeof ASIDE_ROUTES)[number];

export type Route = { kind: 'slide'; id: SlideId } | { kind: 'aside'; id: AsideRoute };

function parseHash(): Route {
  const raw = window.location.hash.replace(/^#\/?/, '');
  const aside = ASIDE_ROUTES.find((r) => r === raw);
  if (aside) return { kind: 'aside', id: aside };
  const slide = SLIDES.find((s) => s.id === raw);
  return { kind: 'slide', id: slide ? slide.id : 'cover' };
}

/**
 * Hash routing, slug-based. Slugs rather than indices so `#/roi` survives
 * inserting a slide ahead of it, and hash rather than history so the built
 * deck needs no rewrite rule on any host — and still works from a file.
 */
export function useDeckNav() {
  const [route, setRoute] = useState<Route>(parseHash);
  /** Feeds the directional slide variants. */
  const [dir, setDir] = useState<1 | -1>(1);

  useEffect(() => {
    const onHash = () => {
      const next = parseHash();
      setRoute((prev) => {
        if (prev.kind === 'slide' && next.kind === 'slide') {
          const a = SLIDES.findIndex((s) => s.id === prev.id);
          const b = SLIDES.findIndex((s) => s.id === next.id);
          setDir(b >= a ? 1 : -1);
        }
        return next;
      });
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const index = route.kind === 'slide' ? SLIDES.findIndex((s) => s.id === route.id) : -1;

  const goTo = useCallback((id: string) => {
    window.location.hash = `#/${id}`;
  }, []);

  const goBy = useCallback(
    (delta: 1 | -1) => {
      /* From an aside screen, an arrow returns to the flow rather than
         stepping blindly — the presenter pressed a key to get out. */
      if (route.kind === 'aside') {
        goTo('cover');
        return;
      }
      const next = Math.min(SLIDES.length - 1, Math.max(0, index + delta));
      if (next !== index) goTo(SLIDES[next].id);
    },
    [route.kind, index, goTo],
  );

  const first = useCallback(() => goTo(SLIDES[0].id), [goTo]);
  const last = useCallback(() => goTo(SLIDES[SLIDES.length - 1].id), [goTo]);

  return { route, dir, index, goTo, goBy, first, last };
}
