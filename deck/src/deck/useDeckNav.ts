import { useCallback, useEffect, useState } from 'react';
import { FLOW_SLIDES, SLIDES } from '../content/slides';
import type { SlideId } from '../content/types';

/** Screens that live outside the pitch flow and off the timing rail. */
export const ASIDE_ROUTES = ['qa', 'audit', 'quality', 'leavebehind', 'notes-print', 'typecheck'] as const;
export type AsideRoute = (typeof ASIDE_ROUTES)[number];

export type Route = { kind: 'slide'; id: SlideId } | { kind: 'aside'; id: AsideRoute };

function resolveSlideId(raw: string): SlideId {
  const slide = SLIDES.find((s) => s.id === raw);
  if (!slide) return 'cover';
  if (!slide.hiddenInFlow) return slide.id;
  /* Hidden slides stay in the deck for leave-behind and typecheck, but a
     bookmark or an old cue card should land on the nearest in-flow neighbour. */
  const idx = SLIDES.findIndex((s) => s.id === raw);
  for (let i = idx + 1; i < SLIDES.length; i++) {
    if (!SLIDES[i].hiddenInFlow) return SLIDES[i].id;
  }
  for (let i = idx - 1; i >= 0; i--) {
    if (!SLIDES[i].hiddenInFlow) return SLIDES[i].id;
  }
  return 'cover';
}

function parseHash(): Route {
  const raw = window.location.hash.replace(/^#\/?/, '');
  const aside = ASIDE_ROUTES.find((r) => r === raw);
  if (aside) return { kind: 'aside', id: aside };
  return { kind: 'slide', id: resolveSlideId(raw) };
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
    const raw = window.location.hash.replace(/^#\/?/, '');
    if (ASIDE_ROUTES.includes(raw as AsideRoute)) return;
    const resolved = resolveSlideId(raw);
    if (raw && raw !== resolved) {
      window.location.replace(`#/${resolved}`);
    }
  }, []);

  useEffect(() => {
    const onHash = () => {
      const next = parseHash();
      setRoute((prev) => {
        if (prev.kind === 'slide' && next.kind === 'slide') {
          const a = FLOW_SLIDES.findIndex((s) => s.id === prev.id);
          const b = FLOW_SLIDES.findIndex((s) => s.id === next.id);
          setDir(b >= a ? 1 : -1);
        }
        return next;
      });
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const flowIndex = route.kind === 'slide' ? FLOW_SLIDES.findIndex((s) => s.id === route.id) : -1;

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
      const next = Math.min(FLOW_SLIDES.length - 1, Math.max(0, flowIndex + delta));
      if (next !== flowIndex) goTo(FLOW_SLIDES[next].id);
    },
    [route.kind, flowIndex, goTo],
  );

  const first = useCallback(() => goTo(FLOW_SLIDES[0].id), [goTo]);
  const last = useCallback(() => goTo(FLOW_SLIDES[FLOW_SLIDES.length - 1].id), [goTo]);

  return { route, dir, flowIndex, goTo, goBy, first, last };
}
