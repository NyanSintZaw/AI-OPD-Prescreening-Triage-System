import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import {
  ArrowRight,
  Brain,
  ClipboardList,
  Clock3,
  HeartPulse,
  Hospital,
  Languages,
  Map as MapIcon,
  MessagesSquare,
  Mic,
  Navigation,
  Printer,
  Stethoscope,
  Thermometer,
  Users,
  X,
} from 'lucide-react';
import { KioskFrame } from '../components/kiosk/KioskFrame';
import { StatCounter } from '../components/kiosk/StatCounter';
import { HospitalMapViewer } from '../components/HospitalMapViewer';
import { useLanguage } from '../hooks/useSession';
import { useKioskStats } from '../hooks/useKioskStats';
import { prewarmVoiceCall } from '../hooks/voicePrewarm';

/** Rotating pitch headlines + the how-it-works step they highlight. */
const AD_KEYS = ['kioskAd1', 'kioskAd2', 'kioskAd3'] as const;
const ROTATE_MS = 4500;

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
    { icon: <Mic size={28} strokeWidth={2.2} />, name: t('kioskHow1'), sub: t('kioskHow1Sub') },
    { icon: <Brain size={28} strokeWidth={2.2} />, name: t('kioskHow2'), sub: t('kioskHow2Sub') },
    { icon: <Hospital size={28} strokeWidth={2.2} />, name: t('kioskHow3'), sub: t('kioskHow3Sub') },
  ];

  const featChips = [
    { icon: <Mic size={18} />, label: t('kioskFeatVoice') },
    { icon: <Languages size={18} />, label: t('kioskFeatLang') },
    { icon: <Clock3 size={18} />, label: t('kioskFeatTime') },
    { icon: <Printer size={18} />, label: t('kioskFeatSlip') },
  ];

  return (
    <KioskFrame language={language} onLanguageChange={setLanguage}>
      {/* Ambient floating icons on the canvas edges (decorative only). */}
      <div className="k-floats" aria-hidden="true">
        <Stethoscope className="k-float-ico" size={64} style={{ top: '12%', left: '4%' }} />
        <HeartPulse
          className="k-float-ico"
          size={56}
          style={{ top: '64%', left: '9%', animationDelay: '1.6s' }}
        />
        <Thermometer
          className="k-float-ico"
          size={52}
          style={{ top: '18%', right: '6%', animationDelay: '0.9s' }}
        />
        <ClipboardList
          className="k-float-ico"
          size={60}
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
                  <ArrowRight size={30} strokeWidth={2.4} />
                </motion.span>
              </motion.button>

              <button type="button" className="k-btn secondary" onClick={() => setShowMap(true)}>
                <MapIcon size={24} strokeWidth={2.2} aria-hidden="true" />
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

        {/* Bottom band: live counters + disclaimer */}
        <div className="k-home-band">
          <div className="k-today">
            <span className="k-today-label">{t('kioskTodayTitle')}</span>
            <div className="k-stats">
              <StatCounter
                value={stats.visitors_today}
                label={t('kioskStatVisitors')}
                icon={<Users size={24} strokeWidth={2.2} />}
                accent="blue"
              />
              <StatCounter
                value={stats.navigated_today}
                label={t('kioskStatNavigated')}
                icon={<Navigation size={24} strokeWidth={2.2} />}
                accent="green"
              />
              <StatCounter
                value={stats.sessions_today}
                label={t('kioskStatSessions')}
                icon={<MessagesSquare size={24} strokeWidth={2.2} />}
                accent="amber"
              />
            </div>
          </div>
          <p className="k-home-footer">{t('disclaimer')}</p>
        </div>
      </div>

      {showMap && (
        <div className="k-overlay" role="dialog" aria-modal="true">
          <div className="k-overlay-head">
            <span className="k-overlay-title">{t('kioskViewMap')}</span>
            <button type="button" className="k-exit" onClick={() => setShowMap(false)}>
              <X size={20} aria-hidden="true" />
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
