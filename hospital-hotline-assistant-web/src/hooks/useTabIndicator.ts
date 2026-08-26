import { useEffect } from 'react';

/**
 * Makes the active mark **travel** instead of teleport — on the tab bars, and
 * on the segmented filter groups (7/14/30 days, pending/reviewed/all).
 *
 * Each tab used to draw its own `border-block-end`, switched on when it became
 * active. That makes the mark vanish from one tab and reappear under another
 * with nothing joining the two, so the eye has to re-find it on every switch.
 * One bar that moves says where you were and where you are in a single gesture.
 *
 * Why a document-wide observer rather than a `<Tabs>` component: six surfaces
 * render this markup (the criteria book, the review dialog, the session detail,
 * the admin board, the device settings and the hospital DB panel) and they are
 * being edited by other work in parallel. This adds the behaviour to all six —
 * and to any that appear later — without touching one of them. The trade is
 * that it reads the DOM instead of props, which is why it only ever *writes*
 * custom properties and never changes layout.
 *
 * Mount once, at the app root.
 */

/** The two strips that carry a moving mark, and how to find the live one in
 *  each. Tabs flag themselves with `aria-selected`; the filter chips only have
 *  a class, which is why `class` is in the mutation filter below. */
const STRIPS = [
  { strip: '.tabs[role="tablist"]', active: '.tab[aria-selected="true"], .tab.active' },
  { strip: '.chip-group', active: '.filter-chip.active' },
] as const;

function measure(strip: HTMLElement, activeSelector: string) {
  const active = strip.querySelector<HTMLElement>(activeSelector);
  if (!active) {
    strip.removeAttribute('data-tab-ready');
    return;
  }
  /* `offsetLeft`/`offsetTop` are relative to the offsetParent's padding edge,
     and so is an absolutely positioned `::after` — so the two agree with no
     correction, including inside the dialog's padded strip. The bar sits on
     the tab's own bottom edge rather than the container's, which is what makes
     it land correctly when the row wraps onto a second line. */
  strip.style.setProperty('--tab-x', `${active.offsetLeft}px`);
  strip.style.setProperty('--tab-w', `${active.offsetWidth}px`);
  strip.style.setProperty('--tab-h', `${active.offsetHeight}px`);
  // Two shapes off one measurement: the tab bar draws a 2px rule on the
  // active tab's bottom edge, the filter groups slide a full-size pill behind
  // it. So `--tab-y` is the tab's top and the rule offsets itself in CSS.
  strip.style.setProperty('--tab-y', `${active.offsetTop}px`);
  // Hidden until the first measurement, or the bar starts at x=0 and slides in
  // from under the leftmost tab on mount.
  strip.setAttribute('data-tab-ready', 'true');
}

export function useTabIndicator(): void {
  useEffect(() => {
    let frame = 0;
    const resize = new ResizeObserver(schedule);

    function measureAll() {
      frame = 0;
      for (const kind of STRIPS) {
        document.querySelectorAll<HTMLElement>(kind.strip).forEach((strip) => {
          resize.observe(strip); // idempotent — re-observing the same node is a no-op
          measure(strip, kind.active);
        });
      }
    }

    function schedule() {
      // Coalesced: a tab switch flips `aria-selected` on two tabs at once, and
      // a mount can add a whole strip's worth of nodes in one commit.
      if (frame) return;
      frame = requestAnimationFrame(measureAll);
    }

    schedule();

    const mutations = new MutationObserver(schedule);
    mutations.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      // `class` is the chatty one, but the filter chips carry their state
      // there and nothing else in this app toggles classes on a loop. Every
      // hit is coalesced into one rAF, and a pass reads a handful of nodes.
      attributeFilter: ['aria-selected', 'class'],
    });
    window.addEventListener('resize', schedule);

    // Web fonts land after first paint and change every tab's width. Without
    // this the bar keeps the width it measured against the fallback face.
    void document.fonts?.ready.then(schedule);

    return () => {
      if (frame) cancelAnimationFrame(frame);
      mutations.disconnect();
      resize.disconnect();
      window.removeEventListener('resize', schedule);
    };
  }, []);
}
