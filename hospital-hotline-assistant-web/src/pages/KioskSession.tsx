import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AnimatePresence, motion } from 'framer-motion';
import { CheckCircle, HandHeart, HouseLine, Printer } from '@phosphor-icons/react';
import { api } from '../api';
import { KioskFrame } from '../components/kiosk/KioskFrame';
import { Stepper, type KioskStep } from '../components/kiosk/Stepper';
import { LanguageSelect } from '../components/kiosk/LanguageSelect';
import { VisitIdCapture } from '../components/kiosk/VisitIdCapture';
import { ConversationStage } from '../components/kiosk/ConversationStage';
import { RecommendationCard } from '../components/RecommendationCard';
import { toAssessment, type ChatAssessment } from '../hooks/useChat';
import { useLanguage, useSessionStorage, setStoredPatientName } from '../hooks/useSession';
import { useVoiceCall } from '../hooks/useVoiceCall';
import { useIdleReset } from '../hooks/useIdleReset';
import { openPatientSlip } from '../utils/openSlip';
import type { AppLanguage } from '../i18n/resources';

type Phase = 'language' | 'visit' | 'hello' | 'conversation' | 'result';

const IDLE_GRACE_SECONDS = 15;

const phaseTransition = {
  initial: { opacity: 0, x: 32 },
  animate: { opacity: 1, x: 0 },
  exit: { opacity: 0, x: -32 },
  transition: { duration: 0.3, ease: 'easeOut' as const },
};

/**
 * The kiosk patient journey:
 * choose language → enter visit ID → personal greeting → AI symptom
 * conversation (incl. vital-sign prompts) → routing result → auto-reset.
 *
 * The session is created only AFTER the language tap, so the screening
 * engine speaks the chosen language and abandoned language screens don't
 * leave orphan sessions behind.
 */
export function KioskSession() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { language, setLanguage } = useLanguage();
  const { sessionId, setSessionId } = useSessionStorage();

  const [phase, setPhase] = useState<Phase>('language');
  const [creating, setCreating] = useState(false);
  const [linking, setLinking] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [patientName, setPatientName] = useState<string | null>(null);
  const [replyOptions, setReplyOptions] = useState<Array<{ id: string; label: string }>>([]);
  const [measurementVital, setMeasurementVital] = useState<string | null>(null);
  const [assessment, setAssessment] = useState<ChatAssessment | null>(null);
  const [startFailed, setStartFailed] = useState(false);

  const startedRef = useRef(false);
  const slipRef = useRef(false);

  // ── Voice conversation engine ────────────────────────────────────────────
  const voiceCall = useVoiceCall({
    sessionId,
    language,
    onQuestionOptions: (options) => setReplyOptions(options),
    onMeasurementRequest: (vital) => {
      setMeasurementVital(vital);
      setReplyOptions([]);
    },
    onAssessmentComplete: (payload) => {
      void (async () => {
        try {
          const departments = await api.listDepartments();
          const deptMap = new Map(
            departments.map((d) => [
              d.id,
              { name: language === 'th' ? d.name_th ?? d.name_en : d.name_en, code: d.code },
            ]),
          );
          setAssessment(toAssessment(payload, deptMap));
        } catch {
          setAssessment(toAssessment(payload, new Map()));
        }
        setReplyOptions([]);
        setMeasurementVital(null);
        setPhase('result');
      })();
    },
  });

  // ── Language phase: pick → create the session in that language ──────────
  const handleLanguageSelect = useCallback(
    async (lang: AppLanguage) => {
      if (creating) return;
      setCreating(true);
      setLanguage(lang);
      try {
        const session = await api.createSession({
          language: lang,
          user_agent: navigator.userAgent,
        });
        setSessionId(session.id);
        setStoredPatientName(null);
        setPhase('visit');
      } catch {
        navigate('/kiosk');
      } finally {
        setCreating(false);
      }
    },
    [creating, setLanguage, setSessionId, navigate],
  );

  // ── Visit phase handlers ─────────────────────────────────────────────────
  const handleVisitSubmit = useCallback(
    async (visitId: string) => {
      if (!sessionId) return;
      setLinking(true);
      setNotFound(false);
      try {
        const res = await api.linkVisit(sessionId, visitId);
        if (res.linked) {
          if (res.patient_name) {
            setPatientName(res.patient_name);
            setStoredPatientName(res.patient_name);
          }
          setPhase('hello');
        } else {
          setNotFound(true);
        }
      } catch {
        setNotFound(true);
      } finally {
        setLinking(false);
      }
    },
    [sessionId],
  );

  const handleSkip = useCallback(() => {
    setPatientName(null);
    setPhase('hello');
  }, []);

  // ── Greeting phase: a real moment, then auto-advance ────────────────────
  useEffect(() => {
    if (phase !== 'hello') return;
    const timer = setTimeout(() => setPhase('conversation'), patientName ? 3000 : 2200);
    return () => clearTimeout(timer);
  }, [phase, patientName]);

  // Start the mic pipeline once we enter the conversation phase. A failure
  // (mic denied/busy) flips startFailed so the stage shows a retry screen
  // instead of hanging on "connecting".
  useEffect(() => {
    if (phase !== 'conversation' || !sessionId || startedRef.current) return;
    if (!voiceCall.supported) return;
    startedRef.current = true;
    void voiceCall.start().catch(() => setStartFailed(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, sessionId, voiceCall.supported]);

  const handleRetryVoice = useCallback(() => {
    setStartFailed(false);
    void voiceCall.start().catch(() => setStartFailed(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Tear the call down if the component unmounts mid-conversation.
  useEffect(() => {
    return () => {
      void voiceCall.end();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Print the patient slip once, when the result lands.
  useEffect(() => {
    if (phase !== 'result' || !sessionId || slipRef.current) return;
    slipRef.current = true;
    void api.updateSession(sessionId, { status: 'completed' }).catch(() => undefined);
    openPatientSlip(sessionId);
  }, [phase, sessionId]);

  // ── Reset / exit ─────────────────────────────────────────────────────────
  const resetToHome = useCallback(() => {
    void voiceCall.end();
    setSessionId(null);
    navigate('/kiosk');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigate, setSessionId]);

  const idle = useIdleReset({
    enabled: phase !== 'result', // result screen waits on the patient explicitly
    warnAfterMs: phase === 'conversation' ? 60000 : 45000,
    graceMs: IDLE_GRACE_SECONDS * 1000,
    onReset: resetToHome,
  });

  // ── Render ───────────────────────────────────────────────────────────────
  const step: KioskStep | null =
    phase === 'visit' ? 0 : phase === 'hello' || phase === 'conversation' ? 1 : phase === 'result' ? 2 : null;

  const ringCircumference = 2 * Math.PI * 42;

  return (
    <KioskFrame
      language={language}
      onLanguageChange={setLanguage}
      // On the language phase the Exit control lives below the language
      // cards instead of crowding the brand lockup in the top bar.
      onExit={phase === 'language' ? undefined : resetToHome}
      hideLanguage={phase === 'language'}
      center={step !== null ? <Stepper current={step} /> : undefined}
    >
      <AnimatePresence mode="wait">
        {phase === 'language' && (
          <motion.div key="language" {...phaseTransition} style={{ width: '100%', display: 'flex', justifyContent: 'center' }}>
            <LanguageSelect
              onSelect={(lang) => void handleLanguageSelect(lang)}
              busy={creating}
              onExit={resetToHome}
            />
          </motion.div>
        )}

        {phase === 'visit' && (
          <motion.div key="visit" {...phaseTransition} style={{ width: '100%', display: 'flex', justifyContent: 'center' }}>
            <VisitIdCapture
              language={language}
              onSubmit={handleVisitSubmit}
              onSkip={handleSkip}
              linking={linking}
              notFound={notFound}
            />
          </motion.div>
        )}

        {phase === 'hello' && (
          <motion.div
            key="hello"
            className="k-hello"
            initial={{ opacity: 0, scale: 0.94 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.35, ease: 'easeOut' }}
          >
            <motion.span
              className="k-hello-badge"
              initial={{ scale: 0.6, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ type: 'spring', stiffness: 280, damping: 18, delay: 0.1 }}
            >
              <HandHeart size={52} weight="duotone" aria-hidden="true" />
            </motion.span>
            <h2 className="k-hello-name">
              {patientName
                ? t('kioskVisitLinkedHello', { name: patientName })
                : t('kioskWelcome')}
            </h2>
            <p className="k-hello-lead">{t('kioskHelloLead')}</p>
          </motion.div>
        )}

        {phase === 'conversation' && (
          <motion.div key="conversation" {...phaseTransition} style={{ width: '100%', minHeight: '100%' }}>
            {voiceCall.supported ? (
              <ConversationStage
                language={language}
                state={voiceCall.state}
                lastReply={voiceCall.lastReply}
                lastTranscript={voiceCall.lastTranscript}
                replyOptions={replyOptions}
                onTapReply={(label) => {
                  setReplyOptions([]);
                  voiceCall.tapReply(label);
                }}
                onDone={voiceCall.sendTurn}
                onEnd={resetToHome}
                measurementVital={measurementVital}
                onMeasurementSubmit={(text) => {
                  setMeasurementVital(null);
                  setReplyOptions([]);
                  voiceCall.submitMeasurement(text);
                }}
                errorText={voiceCall.error}
                hasError={startFailed}
                onRetry={handleRetryVoice}
              />
            ) : (
              <div className="k-hello" style={{ height: '100%', justifyContent: 'center' }}>
                <p className="k-hello-lead">{t('callNotSupported')}</p>
                <button type="button" className="k-btn primary" onClick={resetToHome}>
                  <HouseLine size={22} weight="bold" aria-hidden="true" /> {t('kioskResultFinish')}
                </button>
              </div>
            )}
          </motion.div>
        )}

        {phase === 'result' && (
          <motion.div key="result" className="k-result" {...phaseTransition}>
            <div className="k-result-banner">
              <motion.span
                initial={{ scale: 0.5, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ type: 'spring', stiffness: 300, damping: 18 }}
                style={{ display: 'grid', placeItems: 'center' }}
              >
                <CheckCircle size={46} weight="duotone" aria-hidden="true" />
              </motion.span>
              <div>
                <h2>{t('kioskResultTitle')}</h2>
                <p>{t('kioskResultSubtitle')}</p>
              </div>
            </div>

            {assessment && (
              <div className="k-card k-result-card">
                <RecommendationCard assessment={assessment} autoOpenMap />
              </div>
            )}

            <div className="k-result-actions">
              <button
                type="button"
                className="k-btn secondary"
                onClick={() => sessionId && openPatientSlip(sessionId)}
              >
                <Printer size={22} weight="duotone" aria-hidden="true" /> {t('kioskResultPrint')}
              </button>
              <button type="button" className="k-btn primary xl" onClick={resetToHome}>
                <HouseLine size={24} weight="bold" aria-hidden="true" /> {t('kioskResultFinish')}
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Idle "are you still there?" prompt with a countdown ring */}
      {idle.warning && (
        <div className="k-modal-backdrop">
          <div className="k-modal" role="alertdialog" aria-modal="true">
            <div className="k-ring" aria-hidden="true">
              <svg width="96" height="96" viewBox="0 0 96 96">
                <circle className="k-ring-track" cx="48" cy="48" r="42" />
                <circle
                  className="k-ring-bar"
                  cx="48"
                  cy="48"
                  r="42"
                  strokeDasharray={ringCircumference}
                  strokeDashoffset={
                    ringCircumference * (1 - idle.secondsLeft / IDLE_GRACE_SECONDS)
                  }
                />
              </svg>
              <span className="k-ring-num">{idle.secondsLeft}</span>
            </div>
            <h3>{t('kioskIdleTitle')}</h3>
            <p>{t('kioskIdleBody')}</p>
            <div className="k-modal-actions">
              <button type="button" className="k-btn primary" onClick={idle.stayActive}>
                {t('kioskIdleStay')}
              </button>
              <button type="button" className="k-btn secondary" onClick={resetToHome}>
                {t('kioskIdleRestart')}
              </button>
            </div>
          </div>
        </div>
      )}
    </KioskFrame>
  );
}
