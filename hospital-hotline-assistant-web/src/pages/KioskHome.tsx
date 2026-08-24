import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { motion, useReducedMotion } from 'framer-motion';
import {
  ArrowRight,
  Brain,
  HandTap,
  Hospital,
  MapTrifold,
  Microphone,
  Printer,
  Timer,
  Translate,
  X,
} from '@phosphor-icons/react';
import { KioskFrame } from '../components/kiosk/KioskFrame';
import { NongMali } from '../design-system/components/NongMali';
import { useLanguage } from '../hooks/useSession';
import { prewarmVoiceCall } from '../hooks/voicePrewarm';

/** Untouched this long and the booth falls back to the attract loop. */
const IDLE_TO_ATTRACT_MS = 90000;

/**
 * Kiosk welcome screen — for a patient who has already walked up to the booth.
 * They are not being sold to, so there is one question, one button, and the
 * facts they need before speaking. The advertising lives on `/kiosk/attract`,
 * which takes over when nobody is here.
 */
export function KioskHome() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { language, setLanguage } = useLanguage();
  const [showMap, setShowMap] = useState(false);
  const reduce = useReducedMotion();

  // Booth hygiene: an abandoned screen must not greet the next patient
  // mid-flow, in the previous visitor's language, or stuck behind the map.
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const arm = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        setShowMap(false);
        setLanguage('th');
        navigate('/kiosk/attract');
      }, IDLE_TO_ATTRACT_MS);
    };
    const events: Array<keyof WindowEventMap> = ['pointerdown', 'keydown', 'touchstart'];
    events.forEach((e) => window.addEventListener(e, arm, { passive: true }));
    arm();
    return () => {
      clearTimeout(timer);
      events.forEach((e) => window.removeEventListener(e, arm));
    };
  }, [navigate, setLanguage]);

  // The wayfinder's own Back button posts carenav:back from inside the iframe.
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      if ((event.data as { type?: string } | null)?.type === 'carenav:back') {
        setShowMap(false);
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  const start = () => {
    // Anchor mic permission + audio playback to this tap so the assistant's
    // voice is never blocked by autoplay policy.
    void prewarmVoiceCall();
    navigate('/kiosk/session');
  };

  // Names only. Each step previously carried a sub-line that restated the
  // name directly above it ("MALI asks a few questions" / "A few quick
  // questions — tap or speak to answer").
  const howSteps = [
    { icon: <Microphone size={26} weight="duotone" />, name: t('kioskHow1') },
    { icon: <Brain size={26} weight="duotone" />, name: t('kioskHow2') },
    { icon: <Hospital size={26} weight="duotone" />, name: t('kioskHow3') },
  ];

  const facts = [
    { icon: <Translate size={22} weight="duotone" />, label: t('kioskFeatLang') },
    { icon: <Timer size={22} weight="duotone" />, label: t('kioskFeatTime') },
    { icon: <Printer size={22} weight="duotone" />, label: t('kioskFeatSlip') },
  ];

  return (
    <KioskFrame language={language} onLanguageChange={setLanguage}>
      {/* Brand background — petal drift, whisper opacity (sparse screens only). */}
      <div className="k-petals mali-texture-petals" aria-hidden="true" />

      <div className="k-home">
        <div className="k-hero-hello">
          <NongMali size={168} motion="nongRiseSway" />
          <span className="k-hero-hello-text">{t('kioskHeroHello')}</span>
        </div>

        <h1 className="k-home-title">{t('kioskHomeTitle')}</h1>

        {/* One line: what happens, and who checks it. */}
        <p className="k-hero-sub">{t('kioskWelcomeSub')}</p>

        {/* Plain facts, deliberately not styled as controls. */}
        <ul className="k-facts">
          {facts.map((fact) => (
            <li key={fact.label} className="k-fact">
              <span className="k-fact-ico" aria-hidden="true">
                {fact.icon}
              </span>
              {fact.label}
            </li>
          ))}
        </ul>

        <div className="k-cta-row">
          <motion.button
            type="button"
            className="k-btn primary xl k-cta-start"
            onClick={start}
            whileTap={{ scale: 0.97 }}
          >
            <HandTap size={34} weight="duotone" aria-hidden="true" />
            {t('kioskTouchStart')}
            <motion.span
              aria-hidden="true"
              style={{ display: 'inline-flex' }}
              animate={reduce ? undefined : { x: [0, 7, 0] }}
              transition={{ duration: 1.6, repeat: Infinity, ease: 'easeInOut' }}
            >
              <ArrowRight size={34} weight="bold" />
            </motion.span>
          </motion.button>
          <button type="button" className="k-btn outline" onClick={() => setShowMap(true)}>
            <MapTrifold size={26} weight="duotone" aria-hidden="true" />
            {t('kioskViewMap')}
          </button>
        </div>

        {/* The three steps, no section label — the numbers already say what
            this is. Information, never menu options. */}
        <div className="k-how">
          <ol className="k-how-steps">
            {howSteps.map((step, i) => (
              <li key={step.name} className={`k-how-step k-how-step--${i + 1}`}>
                <span className="k-how-dot">
                  {i + 1}
                  <span className="k-how-ping" aria-hidden="true" />
                </span>
                <span className="k-how-label">
                  <span className="k-how-ico" aria-hidden="true">{step.icon}</span>
                  <span className="k-how-text">{step.name}</span>
                </span>
              </li>
            ))}
          </ol>
        </div>

        <p className="k-home-footer">{t('disclaimer')}</p>
      </div>

      {showMap && (
        // Backdrop tap closes: on a kiosk a modal with one small exit is a trap.
        <div
          className="k-overlay"
          role="dialog"
          aria-modal="true"
          aria-label={t('kioskViewMap')}
          onClick={() => setShowMap(false)}
        >
          <div className="k-overlay-head">
            <span className="k-overlay-title">{t('kioskViewMap')}</span>
          </div>
          <div
            className="k-overlay-body k-overlay-body-map"
            onClick={(e) => e.stopPropagation()}
          >
            <iframe
              src={`/hospital-map/index.html?lang=${language}`}
              className="k-map-frame"
              title={t('kioskViewMap')}
            />
          </div>
          {/* Exit lives at the bottom, in reach — not in the far top corner. */}
          <button type="button" className="k-exit" onClick={() => setShowMap(false)}>
            <X size={24} weight="bold" aria-hidden="true" />
            {t('kioskClose')}
          </button>
        </div>
      )}
    </KioskFrame>
  );
}
