import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AnimatePresence, animate, motion, useReducedMotion } from 'framer-motion';
import {
  ArrowRight,
  Brain,
  ChatsCircle,
  ClipboardText,
  Heartbeat,
  Hospital,
  MapTrifold,
  Microphone,
  NavigationArrow,
  Printer,
  Stethoscope,
  Thermometer,
  Timer,
  Translate,
  UsersThree,
  X,
} from '@phosphor-icons/react';
import { KioskFrame } from '../components/kiosk/KioskFrame';
import { HospitalMapViewer } from '../components/HospitalMapViewer';
import { useLanguage } from '../hooks/useSession';
import { useKioskStats } from '../hooks/useKioskStats';
import { prewarmVoiceCall } from '../hooks/voicePrewarm';

/** Rotating pitch headlines + the how-it-works step they highlight. */
const AD_KEYS = ['kioskAd1', 'kioskAd2', 'kioskAd3'] as const;
const ROTATE_MS = 4500;

/** Count-up number for the rotating stat banner (snaps under reduced motion). */
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
 * Kiosk attract screen. Sells the service with a rotating benefit headline,
 * an auto-highlighting "how it works" panel, feature chips and a pulsing
 * touch-to-start CTA — constant gentle motion to draw passers-by, all gated
 * behind prefers-reduced-motion.
 */
export function KioskHome() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { language, setLanguage } = useLanguage();
  const stats = useKioskStats();
  const [showMap, setShowMap] = useState(false);
  const reduce = useReducedMotion();

  // One ticker drives both the headline carousel and the active step.
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (reduce) return;
    const timer = setInterval(() => setTick((n) => n + 1), ROTATE_MS);
    return () => clearInterval(timer);
  }, [reduce]);
  const adIdx = tick % AD_KEYS.length;

  const start = () => {
    // Anchor mic permission + audio playback to this tap so the assistant's
    // voice is never blocked by autoplay policy.
    void prewarmVoiceCall();
    navigate('/kiosk/session');
  };

  const howSteps = [
    { icon: <Microphone size={28} weight="duotone" />, name: t('kioskHow1'), sub: t('kioskHow1Sub') },
    { icon: <Brain size={28} weight="duotone" />, name: t('kioskHow2'), sub: t('kioskHow2Sub') },
    { icon: <Hospital size={28} weight="duotone" />, name: t('kioskHow3'), sub: t('kioskHow3Sub') },
  ];

  const featChips = [
    { icon: <Microphone size={18} weight="duotone" />, label: t('kioskFeatVoice') },
    { icon: <Translate size={18} weight="duotone" />, label: t('kioskFeatLang') },
    { icon: <Timer size={18} weight="duotone" />, label: t('kioskFeatTime') },
    { icon: <Printer size={18} weight="duotone" />, label: t('kioskFeatSlip') },
  ];

  return (
    <KioskFrame language={language} onLanguageChange={setLanguage}>
      {/* Ambient floating icons on the canvas edges (decorative only). */}
      <div className="k-floats" aria-hidden="true">
        <Stethoscope className="k-float-ico" size={64} weight="duotone" style={{ top: '12%', left: '4%' }} />
        <Heartbeat
          className="k-float-ico"
          size={56}
          weight="duotone"
          style={{ top: '64%', left: '9%', animationDelay: '1.6s' }}
        />
        <Thermometer
          className="k-float-ico"
          size={52}
          weight="duotone"
          style={{ top: '18%', right: '6%', animationDelay: '0.9s' }}
        />
        <ClipboardText
          className="k-float-ico"
          size={60}
          weight="duotone"
          style={{ top: '70%', right: '4%', animationDelay: '2.4s' }}
        />
      </div>

      <div className="k-home">
        <div className="k-home-main">
          {/* Hero: rotating pitch + chips + CTA */}
          <div className="k-hero">
            <div className="k-ad-head">
              <AnimatePresence mode="wait">
                <motion.h1
                  key={adIdx}
                  className="k-ad-title"
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -20 }}
                  transition={{ duration: 0.5, ease: 'easeOut' }}
                >
                  {t(AD_KEYS[adIdx])}
                </motion.h1>
              </AnimatePresence>
            </div>

            <div className="k-ad-dots" aria-hidden="true">
              {AD_KEYS.map((key, i) => (
                <span key={key} className={`k-ad-dot ${i === adIdx ? 'active' : ''}`} />
              ))}
            </div>

            <div className="k-feat-chips">
              {featChips.map((chip) => (
                <span key={chip.label} className="k-feat-chip">
                  {chip.icon}
                  {chip.label}
                </span>
              ))}
            </div>

            <div className="k-cta-row">
              <motion.button
                type="button"
                className="k-btn primary xl"
                onClick={start}
                whileTap={{ scale: 0.97 }}
                animate={
                  reduce
                    ? undefined
                    : {
                        boxShadow: [
                          '0 10px 24px -10px rgba(63,78,135,0.5), 0 0 0 0 rgba(63,78,135,0.3)',
                          '0 10px 24px -10px rgba(63,78,135,0.5), 0 0 0 18px rgba(63,78,135,0)',
                        ],
                      }
                }
                transition={{ duration: 2, repeat: Infinity }}
              >
                {t('kioskTouchStart')}
                <motion.span
                  aria-hidden="true"
                  style={{ display: 'inline-flex' }}
                  animate={reduce ? undefined : { x: [0, 7, 0] }}
                  transition={{ duration: 1.6, repeat: Infinity, ease: 'easeInOut' }}
                >
                  <ArrowRight size={30} weight="bold" />
                </motion.span>
              </motion.button>

              <button type="button" className="k-btn secondary" onClick={() => setShowMap(true)}>
                <MapTrifold size={24} weight="duotone" aria-hidden="true" />
                {t('kioskViewMap')}
              </button>
            </div>
          </div>

          {/* How it works — steps highlight in sync with the headline. */}
          <div className="k-card k-how">
            <span className="k-how-title">{t('kioskHowTitle')}</span>
            {howSteps.map((step, i) => (
              <div
                key={step.name}
                className={`k-how-step k-how-step--${i + 1} ${i === adIdx ? 'active' : ''}`}
              >
                <span className="k-how-ico">{step.icon}</span>
                <span className="k-how-text">
                  <span className="k-how-name">{step.name}</span>
                  <span className="k-how-sub">{step.sub}</span>
                </span>
                <span className="k-how-num">{i + 1}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Bottom band: rotating full-sentence stat banner + disclaimer */}
        <div className="k-home-band">
          <div className="k-today">
            <span className="k-today-label">{t('kioskTodayTitle')}</span>
            {(() => {
              const statLines = [
                {
                  accent: 'blue',
                  icon: <UsersThree size={34} weight="duotone" />,
                  pre: t('kioskStatSent1Pre'),
                  post: t('kioskStatSent1Post'),
                  sub: t('kioskStatSent1Sub'),
                  value: stats.visitors_today,
                },
                {
                  accent: 'green',
                  icon: <NavigationArrow size={32} weight="duotone" />,
                  pre: t('kioskStatSent2Pre'),
                  post: t('kioskStatSent2Post'),
                  sub: t('kioskStatSent2Sub'),
                  value: stats.navigated_today,
                },
                {
                  accent: 'amber',
                  icon: <ChatsCircle size={34} weight="duotone" />,
                  pre: t('kioskStatSent3Pre'),
                  post: t('kioskStatSent3Post'),
                  sub: t('kioskStatSent3Sub'),
                  value: stats.sessions_today,
                },
              ];
              const line = statLines[adIdx];
              return (
                <div className={`k-stat-banner k-stat-banner--${line.accent}`}>
                  <AnimatePresence mode="wait">
                    <motion.div
                      key={adIdx}
                      className={`k-stat-line k-stat-line--${line.accent}`}
                      initial={{ opacity: 0, y: 18 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -18 }}
                      transition={{ duration: 0.4, ease: 'easeOut' }}
                    >
                      <span className="k-stat-line-ico" aria-hidden="true">
                        {line.icon}
                      </span>
                      <span className="k-stat-line-body">
                        <span className="k-stat-line-text">
                          {line.pre && <>{line.pre} </>}
                          <AnimatedNumber value={line.value} />
                          {line.post && <> {line.post}</>}
                        </span>
                        <span className="k-stat-line-sub">{line.sub}</span>
                      </span>
                    </motion.div>
                  </AnimatePresence>
                </div>
              );
            })()}
          </div>
          <p className="k-home-footer">{t('disclaimer')}</p>
        </div>
      </div>

      {showMap && (
        <div className="k-overlay" role="dialog" aria-modal="true">
          <div className="k-overlay-head">
            <span className="k-overlay-title">{t('kioskViewMap')}</span>
            <button type="button" className="k-exit" onClick={() => setShowMap(false)}>
              <X size={20} weight="bold" aria-hidden="true" />
              {t('kioskClose')}
            </button>
          </div>
          <div className="k-overlay-body">
            <HospitalMapViewer />
          </div>
        </div>
      )}
    </KioskFrame>
  );
}
