import { useCallback, useEffect, useState } from 'react';
import { PITCH_SLIDES, SLIDES } from '../content/slides';
import type { SlideId } from '../content/types';

/** Screens that live outside the pitch flow and off the timing rail. */
export const ASIDE_ROUTES = ['qa', 'audit', 'quality', 'leavebehind', 'notes-print', 'typecheck'] as const;
export type AsideRoute = (typeof ASIDE_ROUTES)[number];

export type Route = { kind: 'slide'; id: SlideId } | { kind: 'aside'; id: AsideRoute };

function parseHash(): Route {
  const raw = window.location.hash.replace(/^#\/?/, '');
  const aside = ASIDE_ROUTES.find((r) => r === raw);
  if (aside) return { kind: 'aside', id: aside };
  /* Every slide is reachable now, appendix included — so the only hash that
     gets redirected is one naming no slide at all, and a stale bookmark on a
     projector lands on the cover rather than a blank stage. */
  const slide = SLIDES.find((s) => s.id === raw);
  return { kind: 'slide', id: slide?.id ?? 'cover' };
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

  const slideIndex = route.kind === 'slide' ? SLIDES.findIndex((s) => s.id === route.id) : -1;

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
      const next = Math.min(SLIDES.length - 1, Math.max(0, slideIndex + delta));
      if (next !== slideIndex) goTo(SLIDES[next].id);
    },
    [route.kind, slideIndex, goTo],
  );

  const first = useCallback(() => goTo(SLIDES[0].id), [goTo]);
  /* End is the end of the PITCH, not the end of the array. A presenter reaching
     for the last slide wants Questions — the appendix behind it is somewhere you
     go on purpose, never somewhere a keystroke drops you. */
  const last = useCallback(() => goTo(PITCH_SLIDES[PITCH_SLIDES.length - 1].id), [goTo]);

  return { route, dir, slideIndex, goTo, goBy, first, last };
}
