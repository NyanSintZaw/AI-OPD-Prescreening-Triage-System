import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AnimatePresence, motion } from 'framer-motion';
import { CheckCircle, HandHeart, HouseLine, PhoneSlash, Printer } from '@phosphor-icons/react';
import { api } from '../api';
import { KioskFrame } from '../components/kiosk/KioskFrame';
import { Stepper, type KioskStep } from '../components/kiosk/Stepper';
import { LanguageSelect } from '../components/kiosk/LanguageSelect';
import { VisitIdCapture } from '../components/kiosk/VisitIdCapture';
import { ConfirmNameStep } from '../components/kiosk/ConfirmNameStep';
import { HistoryIntakeStep, type HistoryIntakeValues } from '../components/kiosk/HistoryIntakeStep';
import { ConversationStage } from '../components/kiosk/ConversationStage';
import { RecommendationCard } from '../components/RecommendationCard';
import { toAssessment, type ChatAssessment } from '../hooks/useChat';
import {
  useLanguage,
  useSessionStorage,
  setStoredPatientName,
  setStoredSessionId,
} from '../hooks/useSession';
import { useVoiceCall } from '../hooks/useVoiceCall';
import { useIdleReset } from '../hooks/useIdleReset';
import { openPatientSlip } from '../utils/openSlip';
import type { AppLanguage } from '../i18n/resources';

type Phase =
  | 'language'
  | 'visit'
  | 'resume'
  | 'confirm'
  | 'history'
  | 'hello'
  | 'conversation'
  | 'result';

interface ResumeOffer {
  visitId: string;
  sessionId: string;
  /** 'active' → continue or start over; 'completed' → start over / reprint. */
  status: string;
  patientName: string | null;
  nameConfirmed: boolean;
  needsHistory: boolean;
  language: AppLanguage;
}

const IDLE_GRACE_SECONDS = 15;

const phaseTransition = {
  initial: { opacity: 0, x: 32 },
  animate: { opacity: 1, x: 0 },
  exit: { opacity: 0, x: -32 },
  transition: { duration: 0.3, ease: 'easeOut' as const },
};

/**
 * The kiosk patient journey:
 * choose language → enter visit ID → (resume if same VN still active) OR
 * personal greeting → AI symptom conversation → routing result → auto-reset.
 *
 * The session is created only AFTER a VN is confirmed as new (or the patient
 * skips VN), so abandoned language screens don't leave orphan sessions and
 * hang-ups can resume via GET /sessions/by-visit/{vn}.
 */
export function KioskSession() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { language, setLanguage } = useLanguage();
  const { sessionId, setSessionId } = useSessionStorage();

  const [phase, setPhase] = useState<Phase>('language');
  const [linking, setLinking] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [linkError, setLinkError] = useState(false);
  // The spoken name-confirm said "no" — VN entry shows a re-enter hint.
  const [identityRejected, setIdentityRejected] = useState(false);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmUnclear, setConfirmUnclear] = useState(false);
  const [needsHistory, setNeedsHistory] = useState(false);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyError, setHistoryError] = useState(false);
  const [patientName, setPatientName] = useState<string | null>(null);
  const [replyOptions, setReplyOptions] = useState<Array<{ id: string; label: string }>>([]);
  const [measurementVital, setMeasurementVital] = useState<string | null>(null);
  const [assessment, setAssessment] = useState<ChatAssessment | null>(null);
  const [startFailed, setStartFailed] = useState(false);
  const [confirmExit, setConfirmExit] = useState(false);
  // Same-day session found for the entered VN — patient chooses what to do.
  const [resumeOffer, setResumeOffer] = useState<ResumeOffer | null>(null);
  // Crisis BP → 15-minute rest before re-measuring; shows the rest screen.
  const [restMinutes, setRestMinutes] = useState<number | null>(null);

  const startedRef = useRef(false);
  const slipRef = useRef(false);
  // The session belonging to THIS kiosk run. A previous run's id may still
  // sit in localStorage (tab closed at the slip screen, reload) — reusing it
  // would leak the previous patient's identity into an anonymous run, so a
  // run only ever uses a session it created itself or one explicitly
  // resumed via GET /sessions/by-visit.
  const runSessionRef = useRef<string | null>(null);

  // Neutralize any stale stored session/name from an earlier run on entry.
  useEffect(() => {
    runSessionRef.current = null;
    setSessionId(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
              {
                name: language === 'th' ? d.name_th ?? d.name_en : d.name_en,
                code: d.code,
                navLine: language === 'th' ? d.nav_line_th : d.nav_line_en,
              },
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
    onIdentity: (payload) => {
      // Outcome of the spoken "you are {name}, right?" gate. Delivered
      // after the AI's line finished playing (drain-committed).
      if (payload.kind === 'rejected') {
        void voiceCall.end();
        startedRef.current = false;
        setPatientName(null);
        setStoredPatientName(null);
        setNeedsHistory(false);
        setReplyOptions([]);
        setNotFound(false);
        setLinkError(false);
        setIdentityRejected(true);
        setPhase('visit');
        return;
      }
      if (payload.needsHistory) {
        // Confirmed, but the first-time history form comes before the
        // interview: end this call; saving the form restarts it.
        void voiceCall.end();
        startedRef.current = false;
        setReplyOptions([]);
        setNeedsHistory(true);
        setPhase('history');
      }
      // Confirmed without history: the same call continues into intake.
    },
    onResumeChoice: (payload) => {
      // Spoken outcome of the continue-vs-start-over gate (drain-committed).
      const offer = resumeOffer;
      if (!offer) return;
      if (payload.kind === 'continue') {
        setResumeOffer(null);
        if (offer.patientName) {
          setPatientName(offer.patientName);
          setStoredPatientName(offer.patientName);
        }
        if (payload.needsHistory) {
          // Bridge handed off to the history form; the call is done.
          void voiceCall.end();
          startedRef.current = false;
          setNeedsHistory(true);
          setPhase('history');
        } else {
          // Same call keeps going (identity gate or intake already speaking).
          setNeedsHistory(offer.needsHistory);
          setPhase('conversation');
        }
        return;
      }
      if (payload.kind === 'start_over') {
        void handleResumeStartOver();
        return;
      }
      // decline / unclear ×2 — the call ends; the on-screen buttons decide.
      void voiceCall.end();
      startedRef.current = false;
    },
  });

  // ── Language phase: pin UI language only — session is created at visit ──
  const handleLanguageSelect = useCallback(
    (lang: AppLanguage) => {
      setLanguage(lang);
      setPhase('visit');
    },
    [setLanguage],
  );

  const ensureSession = useCallback(async (): Promise<string> => {
    // Reuse only within this run (e.g. re-entering a VN after a rejected
    // name confirmation) — never a stored id from a previous run.
    if (runSessionRef.current) return runSessionRef.current;
    const session = await api.createSession({
      language,
      user_agent: navigator.userAgent,
    });
    runSessionRef.current = session.id;
    setSessionId(session.id);
    return session.id;
  }, [language, setSessionId]);

  // Adopt an existing same-day session (patient chose "continue").
  const adoptSession = useCallback(
    (offer: ResumeOffer) => {
      runSessionRef.current = offer.sessionId;
      setSessionId(offer.sessionId);
      setLanguage(offer.language);
      if (offer.patientName) {
        setPatientName(offer.patientName);
        setStoredPatientName(offer.patientName);
      } else {
        setPatientName(null);
        setStoredPatientName(null);
      }
      startedRef.current = false;
      setNeedsHistory(offer.needsHistory);
      if (offer.nameConfirmed) {
        setPhase(offer.needsHistory ? 'history' : 'conversation');
      } else if (offer.patientName) {
        // Unconfirmed name: the voice call opens with the spoken
        // "you are {name}, right?" gate. The screen step remains the
        // no-mic fallback only.
        setConfirmUnclear(false);
        setPhase(voiceCall.supported ? 'conversation' : 'confirm');
      } else {
        setPhase(offer.needsHistory ? 'history' : 'conversation');
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [setLanguage, setSessionId, voiceCall.supported],
  );

  // Create a fresh session and link the VN (first run or "start over").
  const createAndLink = useCallback(
    async (visitId: string) => {
      const id = await ensureSession();
      const res = await api.linkVisit(id, visitId);
      if (res.linked) {
        setNeedsHistory(Boolean(res.is_first_time));
        if (res.patient_name) {
          setPatientName(res.patient_name);
          setStoredPatientName(res.patient_name);
          setConfirmUnclear(false);
          // Voice-first: the AI speaks the confirmation in-call; the
          // ConfirmNameStep screen is only for kiosks without a mic.
          setPhase(voiceCall.supported ? 'conversation' : 'confirm');
        } else {
          setPatientName(null);
          setStoredPatientName(null);
          setPhase(res.is_first_time ? 'history' : 'hello');
        }
      } else {
        // Clean HIS response: this visit ID genuinely isn't registered.
        setNotFound(true);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [ensureSession, voiceCall.supported],
  );

  // ── Visit phase: offer resume when a same-day session exists ────────────
  const handleVisitSubmit = useCallback(
    async (visitId: string) => {
      setLinking(true);
      setNotFound(false);
      setLinkError(false);
      setIdentityRejected(false);
      try {
        const existing = await api.getSessionByVisit(visitId);
        if (existing.found && existing.session) {
          const visitMeta = existing.session.metadata?.visit as
            | { patient_name?: unknown }
            | undefined;
          const name =
            existing.patient_name ||
            (typeof visitMeta?.patient_name === 'string' ? visitMeta.patient_name : null);
          // Never silently resume: the patient decides (continue for an
          // unfinished assessment; start over — or reprint — for a done one).
          // Adopt the old session id now so the voice call can open on it
          // and SPEAK the question (start-over re-nulls runSessionRef).
          runSessionRef.current = existing.session.id;
          setSessionId(existing.session.id);
          setLanguage(existing.session.language);
          startedRef.current = false;
          setResumeOffer({
            visitId,
            sessionId: existing.session.id,
            status: existing.status || existing.session.status || 'active',
            patientName: name,
            nameConfirmed: Boolean(existing.name_confirmed),
            needsHistory: Boolean(existing.needs_history_intake),
            language: existing.session.language as AppLanguage,
          });
          setPhase('resume');
          return;
        }

        await createAndLink(visitId);
      } catch {
        // Thrown exception: couldn't even check (network/server failure) —
        // distinct from "not found" so the patient isn't told to re-enter
        // a correct ID when the real problem is connectivity.
        setLinkError(true);
      } finally {
        setLinking(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [createAndLink, setLanguage, setSessionId],
  );

  const handleResumeContinue = useCallback(() => {
    if (!resumeOffer) return;
    // A tap decides directly — end the spoken gate's call (if any); the
    // adopted phase restarts it with the normal opening.
    void voiceCall.end();
    startedRef.current = false;
    adoptSession(resumeOffer);
    setResumeOffer(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adoptSession, resumeOffer]);

  const handleResumeStartOver = useCallback(async () => {
    if (!resumeOffer || linking) return;
    setLinking(true);
    void voiceCall.end();
    startedRef.current = false;
    // The fresh run must never reuse the old session.
    runSessionRef.current = null;
    try {
      if (resumeOffer.status === 'active') {
        // Retire the abandoned run so it can't be offered again.
        await api
          .updateSession(resumeOffer.sessionId, { status: 'reset' })
          .catch(() => undefined);
      }
      await createAndLink(resumeOffer.visitId);
      setResumeOffer(null);
    } catch {
      setLinkError(true);
      setPhase('visit');
      setResumeOffer(null);
    } finally {
      setLinking(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [createAndLink, linking, resumeOffer]);

  const handleSkip = useCallback(async () => {
    setLinking(true);
    setLinkError(false);
    try {
      await ensureSession();
      setStoredPatientName(null);
      setPatientName(null);
      setPhase('hello');
    } catch {
      setLinkError(true);
    } finally {
      setLinking(false);
    }
  }, [ensureSession]);

  const handleConfirmName = useCallback(
    async (payload: { confirmed?: boolean; text?: string }) => {
      if (!sessionId || confirmBusy) return;
      setConfirmBusy(true);
      setConfirmUnclear(false);
      try {
        const res = await api.confirmVisitName(sessionId, payload);
        if (res.decision === 'yes') {
          setPhase(needsHistory ? 'history' : 'conversation');
          return;
        }
        if (res.decision === 'no' || res.unlinked) {
          setPatientName(null);
          setStoredPatientName(null);
          setNeedsHistory(false);
          setPhase('visit');
          return;
        }
        // uncertain / other — stay on confirm and ask again
        setConfirmUnclear(true);
      } catch {
        setConfirmUnclear(true);
      } finally {
        setConfirmBusy(false);
      }
    },
    [confirmBusy, needsHistory, sessionId],
  );

  const handleHistorySubmit = useCallback(
    async (values: HistoryIntakeValues) => {
      if (!sessionId || historyBusy) return;
      setHistoryBusy(true);
      setHistoryError(false);
      try {
        await api.savePatientHistory(sessionId, values);
        setNeedsHistory(false);
        setPhase('conversation');
      } catch {
        setHistoryError(true);
      } finally {
        setHistoryBusy(false);
      }
    },
    [historyBusy, sessionId],
  );

  const handleHistorySkip = useCallback(() => {
    setNeedsHistory(false);
    setPhase('conversation');
  }, []);

  // Crisis BP → 15-minute rest. End the call, show the rest screen; the
  // session stays active so re-entering the VN offers "continue".
  const handleMeasurementRest = useCallback((seconds: number) => {
    setMeasurementVital(null);
    setReplyOptions([]);
    void voiceCall.end();
    startedRef.current = false;
    setRestMinutes(Math.max(1, Math.ceil(seconds / 60)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Greeting phase (anonymous / skip only): brief beat, then advance ────
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

  // The resume chooser is spoken too: open the call on the old session with
  // the continue-vs-start-over gate. The on-screen buttons stay live as the
  // tap path (and the only path on kiosks without a mic).
  useEffect(() => {
    if (phase !== 'resume' || !resumeOffer || !sessionId || startedRef.current) return;
    if (!voiceCall.supported) return;
    startedRef.current = true;
    void voiceCall
      .start({
        resumePrompt: resumeOffer.status === 'completed' ? 'completed' : 'active',
      })
      .catch(() => undefined); // buttons still work if the mic fails here
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, sessionId, resumeOffer, voiceCall.supported]);

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
    // A finished run must never be picked up by the next patient: drop the
    // stored id now (component state keeps it for the reprint button; the
    // slip page reads its id from the URL).
    setStoredSessionId(null);
    setStoredPatientName(null);
  }, [phase, sessionId]);

  // ── Reset / exit ─────────────────────────────────────────────────────────
  const resetToHome = useCallback(() => {
    setConfirmExit(false);
    void voiceCall.end();
    setSessionId(null);
    navigate('/kiosk');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigate, setSessionId]);

  // Mid-conversation an accidental Exit tap would throw away the whole
  // interview — confirm first. Every other phase exits immediately.
  const requestExit = useCallback(() => {
    if (phase === 'conversation') {
      setConfirmExit(true);
    } else {
      resetToHome();
    }
  }, [phase, resetToHome]);

  const idle = useIdleReset({
    // Also armed on the result screen so a walk-away doesn't leave the
    // previous patient's recommendation on display — just with more slack.
    enabled: true,
    warnAfterMs: phase === 'result' ? 90000 : phase === 'conversation' ? 60000 : 45000,
    graceMs: IDLE_GRACE_SECONDS * 1000,
    onReset: resetToHome,
  });

  // ── Render ───────────────────────────────────────────────────────────────
  const step: KioskStep | null =
    phase === 'visit' || phase === 'resume'
      ? 0
      : phase === 'confirm' || phase === 'history' || phase === 'hello' || phase === 'conversation'
        ? 1
        : phase === 'result'
          ? 2
          : null;

  const ringCircumference = 2 * Math.PI * 42;

  return (
    <KioskFrame
      language={language}
      onLanguageChange={setLanguage}
      // On the language phase the Exit control lives below the language
      // cards instead of crowding the brand lockup in the top bar.
      onExit={phase === 'language' ? undefined : requestExit}
      // The session's language is pinned when it's created — a mid-session
      // toggle would switch the UI while the assistant keeps speaking the
      // chosen language, so the toggle is hidden for the whole session.
      hideLanguage
      center={step !== null ? <Stepper current={step} /> : undefined}
    >
      <AnimatePresence mode="wait">
        {phase === 'language' && (
          <motion.div key="language" {...phaseTransition} style={{ width: '100%', display: 'flex', justifyContent: 'center' }}>
            <LanguageSelect
              onSelect={handleLanguageSelect}
              busy={false}
              onExit={resetToHome}
              error={false}
            />
          </motion.div>
        )}

        {phase === 'visit' && (
          <motion.div key="visit" {...phaseTransition} style={{ width: '100%', display: 'flex', justifyContent: 'center' }}>
            <VisitIdCapture
              language={language}
              onSubmit={handleVisitSubmit}
              onSkip={() => void handleSkip()}
              linking={linking}
              notFound={notFound}
              linkError={linkError}
              identityRejected={identityRejected}
            />
          </motion.div>
        )}

        {phase === 'resume' && resumeOffer && (
          <motion.div key="resume" {...phaseTransition} className="k-hello">
            <motion.span
              className="k-hello-badge"
              initial={{ scale: 0.6, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ type: 'spring', stiffness: 280, damping: 18, delay: 0.1 }}
            >
              <HandHeart size={52} weight="duotone" aria-hidden="true" />
            </motion.span>
            <h2 className="k-hello-name">
              {resumeOffer.status === 'completed'
                ? t('kioskResumeDoneTitle', {
                    name: resumeOffer.patientName ?? t('kioskWelcome'),
                  })
                : t('kioskResumeTitle', {
                    name: resumeOffer.patientName ?? t('kioskWelcome'),
                  })}
            </h2>
            <p className="k-hello-lead">
              {resumeOffer.status === 'completed'
                ? t('kioskResumeDoneLead')
                : t('kioskResumeLead')}
            </p>
            <div className="k-result-actions">
              {resumeOffer.status !== 'completed' && (
                <button
                  type="button"
                  className="k-btn primary xl"
                  onClick={handleResumeContinue}
                  disabled={linking}
                >
                  {t('kioskResumeContinue')}
                </button>
              )}
              <button
                type="button"
                className={`k-btn ${resumeOffer.status === 'completed' ? 'primary xl' : 'secondary'}`}
                onClick={() => void handleResumeStartOver()}
                disabled={linking}
              >
                {linking ? t('loading') : t('kioskResumeStartOver')}
              </button>
              {resumeOffer.status === 'completed' && (
                <button
                  type="button"
                  className="k-btn secondary"
                  onClick={() => openPatientSlip(resumeOffer.sessionId)}
                >
                  <Printer size={22} weight="duotone" aria-hidden="true" />{' '}
                  {t('kioskResumeReprint')}
                </button>
              )}
            </div>
            <button
              type="button"
              className="text-btn"
              onClick={() => {
                void voiceCall.end();
                startedRef.current = false;
                runSessionRef.current = null;
                setResumeOffer(null);
                setPhase('visit');
              }}
              disabled={linking}
            >
              {t('kioskResumeBack')}
            </button>
          </motion.div>
        )}

        {phase === 'confirm' && patientName && (
          <motion.div key="confirm" {...phaseTransition} style={{ width: '100%', display: 'flex', justifyContent: 'center' }}>
            <ConfirmNameStep
              patientName={patientName}
              busy={confirmBusy}
              unclear={confirmUnclear}
              onConfirm={(payload) => void handleConfirmName(payload)}
            />
          </motion.div>
        )}

        {phase === 'history' && (
          <motion.div key="history" {...phaseTransition} style={{ width: '100%', display: 'flex', justifyContent: 'center' }}>
            <HistoryIntakeStep
              busy={historyBusy}
              error={historyError}
              onSubmit={(values) => void handleHistorySubmit(values)}
              onSkip={handleHistorySkip}
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
                onEnd={requestExit}
                onInterrupt={voiceCall.interrupt}
                canInterrupt={!voiceCall.autoEnding}
                measurementVital={measurementVital}
                onMeasurementSubmit={(text) => {
                  setMeasurementVital(null);
                  setReplyOptions([]);
                  voiceCall.submitMeasurement(text);
                }}
                onMeasurementRest={handleMeasurementRest}
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

      {/* Crisis BP → rest 15 minutes; the assessment waits and resumes by VN */}
      {restMinutes !== null && (
        <div className="k-modal-backdrop">
          <div className="k-modal" role="alertdialog" aria-modal="true">
            <h3>{t('kioskRestTitle')}</h3>
            <p>{t('kioskRestBody', { minutes: restMinutes })}</p>
            <p className="muted">{t('kioskRestBody2')}</p>
            <div className="k-modal-actions">
              <button
                type="button"
                className="k-btn primary"
                onClick={() => {
                  setRestMinutes(null);
                  resetToHome();
                }}
              >
                {t('kioskRestOk')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Exit confirmation — an accidental tap must not destroy the interview */}
      {confirmExit && (
        <div className="k-modal-backdrop">
          <div className="k-modal" role="alertdialog" aria-modal="true">
            <h3>{t('kioskExitConfirmTitle')}</h3>
            <p>{t('kioskExitConfirmBody')}</p>
            <div className="k-modal-actions">
              <button type="button" className="k-btn primary" onClick={() => setConfirmExit(false)}>
                {t('kioskExitConfirmNo')}
              </button>
              <button type="button" className="k-btn danger-ghost" onClick={resetToHome}>
                <PhoneSlash size={20} weight="bold" aria-hidden="true" />
                {t('kioskExitConfirmYes')}
              </button>
            </div>
          </div>
        </div>
      )}

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
