import { useEffect, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AnimatePresence, animate, motion, useReducedMotion } from 'framer-motion';
import {
  ChatsCircle,
  HandTap,
  Heartbeat,
  NavigationArrow,
  Printer,
  Translate,
  UsersThree,
} from '@phosphor-icons/react';
import { KioskFrame } from '../components/kiosk/KioskFrame';
import { NongMali } from '../design-system/components/NongMali';
import { useLanguage } from '../hooks/useSession';
import { useKioskStats } from '../hooks/useKioskStats';

/** Rotating pitch headlines. */
const AD_KEYS = ['kioskAd1', 'kioskAd2', 'kioskAd3'] as const;
/* Two tickers, co-prime periods. On one shared tick the headline and the board
   swapped in lockstep, so the whole poster changed at once — two concurrent
   motion sources reading as one lurch. At 7s and 11s they coincide once every
   77s instead of on every swap. */
const AD_MS = 7000;
const BOARD_MS = 11000;

/** Count-up number for the rotating board (snaps under reduced motion). */
function AnimatedNumber({ value }: { value: number }) {
  const reduce = useReducedMotion();
  const [display, setDisplay] = useState(reduce ? value : 0);
  useEffect(() => {
    if (reduce) {
      setDisplay(value);
      return;
    }
    const controls = animate(0, value, {
      duration: 0.9,
      ease: 'easeOut',
      onUpdate: (v) => setDisplay(Math.round(v)),
    });
    return () => controls.stop();
  }, [value, reduce]);
  return <span className="k-stat-line-num">{display.toLocaleString()}</span>;
}

/**
 * The attract loop — what the booth shows when nobody is standing at it.
 * This is the only surface allowed to advertise: the welcome screen behind it
 * is for a patient who has already walked up, so it stays a single question
 * and a single button. Any touch anywhere hands over to the welcome screen.
 *
 * Motion note: the ticker runs regardless of `prefers-reduced-motion` — a
 * motion preference must suppress *transition*, never *content*. Only the
 * enter/exit tweens are flattened.
 */
export function KioskAttract() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { language, setLanguage } = useLanguage();
  const stats = useKioskStats();
  const reduce = useReducedMotion();

  const [adTick, setAdTick] = useState(0);
  const [boardTick, setBoardTick] = useState(0);
  useEffect(() => {
    const a = setInterval(() => setAdTick((n) => n + 1), AD_MS);
    const b = setInterval(() => setBoardTick((n) => n + 1), BOARD_MS);
    return () => {
      clearInterval(a);
      clearInterval(b);
    };
  }, []);
  const adIdx = adTick % AD_KEYS.length;

  const wake = () => navigate('/kiosk');

  // Enter/exit tween, flattened (not removed) under reduced motion.
  const swap = reduce
    ? { initial: { opacity: 1 }, animate: { opacity: 1 }, exit: { opacity: 1 }, transition: { duration: 0 } }
    : {
        initial: { opacity: 0, y: 20 },
        animate: { opacity: 1, y: 0 },
        exit: { opacity: 0, y: -20 },
        transition: { duration: 0.5, ease: 'easeOut' as const },
      };

  type BoardLine = {
    icon: ReactNode;
    kind: 'stat' | 'ad';
    pre?: string;
    post?: string;
    sub: string;
    value?: number;
    text?: string;
  };
  const boardLines: BoardLine[] = [
    {
      icon: <UsersThree size={34} weight="duotone" />,
      kind: 'stat',
      pre: t('kioskStatSent1Pre'),
      post: t('kioskStatSent1Post'),
      sub: t('kioskStatSent1Sub'),
      value: stats.booth_patients_today,
    },
    {
      icon: <Translate size={34} weight="duotone" />,
      kind: 'ad',
      text: t('kioskAdBoard1Text'),
      sub: t('kioskAdBoard1Sub'),
    },
    {
      icon: <NavigationArrow size={32} weight="duotone" />,
      kind: 'stat',
      pre: t('kioskStatSent2Pre'),
      post: t('kioskStatSent2Post'),
      sub: t('kioskStatSent2Sub'),
      value: stats.navigated_today,
    },
    {
      icon: <Printer size={34} weight="duotone" />,
      kind: 'ad',
      text: t('kioskAdBoard2Text'),
      sub: t('kioskAdBoard2Sub'),
    },
    {
      icon: <ChatsCircle size={34} weight="duotone" />,
      kind: 'stat',
      pre: t('kioskStatSent3Pre'),
      post: t('kioskStatSent3Post'),
      sub: t('kioskStatSent3Sub'),
      value: stats.sessions_today,
    },
    {
      icon: <Heartbeat size={34} weight="duotone" />,
      kind: 'ad',
      text: t('kioskAdBoard3Text'),
      sub: t('kioskAdBoard3Sub'),
    },
  ];
  // With every stat at zero — early morning, or the backend down — the three
  // stat slides all collapse to the same "be the first" line. Show the pitches
  // only rather than repeating one message three times per loop.
  const allZero =
    !stats.booth_patients_today && !stats.navigated_today && !stats.sessions_today;
  const lines = allZero ? boardLines.filter((l) => l.kind === 'ad') : boardLines;
  const boardIdx = boardTick % lines.length;
  const line = lines[boardIdx];

  return (
    <KioskFrame language={language} onLanguageChange={setLanguage}>
      <div className="k-petals mali-texture-petals" aria-hidden="true" />

      {/* The whole canvas is the affordance — a passer-by should not have to
          find a target. Keyboard is irrelevant on this hardware, but the
          button element keeps it reachable for bench testing. */}
      <button type="button" className="k-attract" onClick={wake}>
        <NongMali size={200} motion="nongRiseSway" />

        <div className="k-attract-head">
          <AnimatePresence mode="wait">
            <motion.p key={adIdx} className="k-attract-title" {...swap}>
              {t(AD_KEYS[adIdx])}
            </motion.p>
          </AnimatePresence>
        </div>

        <div className="k-attract-board">
          <AnimatePresence mode="wait">
            <motion.div key={boardIdx} className="k-stat-line" {...swap}>
              <span className="k-stat-line-ico" aria-hidden="true">
                {line.icon}
              </span>
              <span className="k-stat-line-body">
                {line.kind === 'ad' ? (
                  <>
                    <span className="k-stat-line-text">{line.text}</span>
                    <span className="k-stat-line-sub">{line.sub}</span>
                  </>
                ) : (
                  <>
                    <span className="k-stat-line-text">
                      {line.pre && <>{line.pre} </>}
                      <AnimatedNumber value={line.value ?? 0} />
                      {line.post && <> {line.post}</>}
                    </span>
                    <span className="k-stat-line-sub">{line.sub}</span>
                  </>
                )}
              </span>
            </motion.div>
          </AnimatePresence>
        </div>

        {/* The ask comes last — it used to sit above the board, so the
            invitation was followed by more content, which undercut it. */}
        <span className="k-attract-cta">
          <HandTap size={34} weight="duotone" aria-hidden="true" />
          {t('kioskAttractTap')}
        </span>
      </button>
    </KioskFrame>
  );
}

