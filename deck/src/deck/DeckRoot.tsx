import { AnimatePresence, motion } from 'framer-motion';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { SLIDES } from '../content/slides';
import { SlideView } from '../layouts/SlideView';
import { FillAudit } from '../screens/FillAudit';
import { QAAppendix } from '../screens/QAAppendix';
import { LeaveBehind } from '../screens/LeaveBehind';
import { QualityAppendix } from '../screens/QualityAppendix';
import { TypeCheck } from '../screens/TypeCheck';
import { DeckMotionProvider } from './motionContext';
import { HelpOverlay } from './HelpOverlay';
import { NotesPanel } from './NotesPanel';
import { OverviewGrid } from './OverviewGrid';
import { ProgressRail } from './ProgressRail';
import { useDeckMotion } from './useDeckMotion';
import { useDeckNav } from './useDeckNav';
import { useKeyboard, type Binding } from './useKeyboard';
import { useStageScale } from './useStageScale';
import { useTimer } from './useTimer';

type Overlay = null | 'help' | 'grid';

export function DeckRoot() {
  const nav = useDeckNav();
  const deckMotion = useDeckMotion();
  const stage = useStageScale();
  const timer = useTimer();

  const [overlay, setOverlay] = useState<Overlay>(null);
  const [notes, setNotes] = useState(false);
  const [blackout, setBlackout] = useState(false);
  /* Elapsed within the current slide, so the rail can show the budget being
     spent rather than only where we are in the deck. */
  const [slideEnteredAt, setSlideEnteredAt] = useState(0);

  const slide = nav.route.kind === 'slide' ? SLIDES.find((s) => s.id === nav.route.id) ?? null : null;
  const slideId = slide?.id;

  useEffect(() => {
    setSlideEnteredAt(timer.elapsed);
    // Reset only when the slide itself changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slideId]);

  const elapsedInSlide = Math.max(0, timer.elapsed - slideEnteredAt);

  /* The aside screens scroll. Changing the hash makes the browser hunt for an
     anchor and leaves the container part-scrolled, so a screen opened with `A`
     can start halfway down its own table. Reset it on every route change. */
  const asideRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const top = () => {
      if (asideRef.current) asideRef.current.scrollTop = 0;
    };
    top();
    /* Again next frame: the browser's own fragment scroll lands after this
       effect on a cold load straight to #/audit. */
    const raf = requestAnimationFrame(top);
    return () => cancelAnimationFrame(raf);
  }, [nav.route.id]);

  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void document.documentElement.requestFullscreen();
  }, []);

  const bindings = useMemo<Binding[]>(() => {
    const closeOrNothing = () => setOverlay(null);
    return [
      { keys: ['Escape'], run: closeOrNothing },
      { keys: ['ArrowRight', 'ArrowDown', ' ', 'PageDown'], run: () => nav.goBy(1) },
      { keys: ['ArrowLeft', 'ArrowUp', 'PageUp'], run: () => nav.goBy(-1) },
      { keys: ['Home'], run: nav.first },
      { keys: ['End'], run: nav.last },
      /* Digit jumps are handled by their own listener below — the binding
         table matches on key names and cannot pass the digit through. */
      { keys: ['o', 'O'], run: () => setOverlay((o) => (o === 'grid' ? null : 'grid')) },
      { keys: ['?', '/'], run: () => setOverlay((o) => (o === 'help' ? null : 'help')) },
      { keys: ['n', 'N'], run: () => setNotes((v) => !v) },
      { keys: ['f', 'F'], run: toggleFullscreen },
      { keys: ['t', 'T'], run: timer.toggle },
      { keys: ['r', 'R'], run: timer.reset },
      { keys: ['b', 'B', '.'], run: () => setBlackout((v) => !v) },
      { keys: ['a', 'A'], run: () => nav.goTo('audit') },
      { keys: ['q', 'Q'], run: () => nav.goTo('qa') },
      { keys: ['v', 'V'], run: () => nav.goTo('quality') },
      { keys: ['m', 'M'], run: deckMotion.toggleForced },
    ];
  }, [nav, timer, deckMotion, toggleFullscreen]);

  useKeyboard(bindings);

  /* Digit jumps need the pressed key itself, which the binding table cannot
     carry, so they get their own tiny listener. */
  useEffect(() => {
    const onDigit = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (!/^[0-9]$/.test(e.key)) return;
      const n = e.key === '0' ? 10 : Number(e.key);
      const target = SLIDES.find((s) => s.number === n);
      if (target) nav.goTo(target.id);
    };
    window.addEventListener('keydown', onDigit);
    return () => window.removeEventListener('keydown', onDigit);
  }, [nav]);

  /* The deck is driven from a keyboard or a remote in the room, but the link
     gets opened on phones. Horizontal swipe navigates; vertical is left alone
     so the aside screens keep scrolling. */
  const swipeFrom = useRef<{ x: number; y: number } | null>(null);
  const onSwipeEnd = (e: React.PointerEvent) => {
    const from = swipeFrom.current;
    swipeFrom.current = null;
    if (!from) return;
    const dx = e.clientX - from.x;
    if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(e.clientY - from.y)) nav.goBy(dx < 0 ? 1 : -1);
  };

  return (
    <DeckMotionProvider value={deckMotion}>
    <div className={`mali-root deck-root${notes ? ' has-notes' : ''}`}>
      <div
        className="deck-viewport"
        onPointerDown={(e) => {
          if (e.pointerType === 'touch') swipeFrom.current = { x: e.clientX, y: e.clientY };
        }}
        onPointerUp={onSwipeEnd}
        onPointerCancel={() => (swipeFrom.current = null)}
      >
        <div
          className="deck-stage"
          style={
            { '--stage-scale': stage.scale, '--stage-h': `${stage.height}px` } as React.CSSProperties
          }
        >
          <div className="deck-aurora" aria-hidden="true" />
          <div className="deck-petals mali-texture-petals" aria-hidden="true" />

          {/* mode="wait" so the outgoing slide clears before the next arrives —
              two slides of Thai on screen at once is unreadable. */}
          <AnimatePresence mode="wait" custom={nav.dir} initial={false}>
            {slide ? (
              <motion.div
                key={slide.id}
                className={`deck-slide deck-slide--${slide.layout}`}
                custom={nav.dir}
                variants={deckMotion.slide}
                initial="enter"
                animate="center"
                exit="exit"
              >
                <SlideView slide={slide} />
              </motion.div>
            ) : (
              <motion.div
                key={nav.route.id}
                ref={asideRef}
                className="deck-slide deck-slide--aside"
                variants={deckMotion.slide}
                custom={1}
                initial="enter"
                animate="center"
                exit="exit"
              >
                {nav.route.id === 'audit' && <FillAudit />}
                {nav.route.id === 'qa' && <QAAppendix />}
                {nav.route.id === 'quality' && <QualityAppendix />}
                {nav.route.id === 'leavebehind' && <LeaveBehind />}
                {nav.route.id === 'typecheck' && <TypeCheck />}
              </motion.div>
            )}
          </AnimatePresence>

          {slide && <ProgressRail currentId={slide.id} elapsedInSlide={elapsedInSlide} />}

          {blackout && <div className="deck-blackout" aria-hidden="true" />}
        </div>
      </div>

      {notes && slide && (
        <NotesPanel
          slide={slide}
          index={nav.slideIndex}
          elapsed={timer.elapsed}
          elapsedInSlide={elapsedInSlide}
          timerRunning={timer.running}
          reducedMotionWarning={deckMotion.prefersReduced && !deckMotion.forced}
        />
      )}

      <div className="d-rotate">
        <span>หมุนเครื่องเป็นแนวนอนเพื่อดูสไลด์เต็มจอ</span>
        <span>Rotate to landscape · swipe to change slide</span>
      </div>

      {overlay === 'help' && <HelpOverlay onClose={() => setOverlay(null)} />}
      {overlay === 'grid' && (
        <OverviewGrid
          currentId={slide?.id ?? ''}
          onPick={(id) => nav.goTo(id)}
          onClose={() => setOverlay(null)}
        />
      )}
    </div>
    </DeckMotionProvider>
  );
}
