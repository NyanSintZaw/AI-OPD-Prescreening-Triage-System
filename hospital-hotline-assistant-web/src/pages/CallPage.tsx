import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import { Layout } from '../components/Layout';
import { PatientIdPassPopup } from '../components/PatientIdPass';
import { RecommendationCard } from '../components/RecommendationCard';
import { useChat, toAssessment, type ChatAssessment } from '../hooks/useChat';
import { useLanguage, useSessionStorage } from '../hooks/useSession';
import { useVoiceCall } from '../hooks/useVoiceCall';

function PhoneIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.8-.4 1.2-.2 1 .4 2 .7 3 .9.4.1.7.4.7.9V20c0 .6-.4 1-1 1C10.1 21 3 13.9 3 5c0-.6.4-1 1-1h3.5c.5 0 .9.3 1 .8.2 1 .5 2 1 3 .1.4 0 .9-.3 1.2L6.6 10.8z" />
    </svg>
  );
}

function HangUpIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M12 8c-3 0-5.7 1-7.9 2.5-.4.3-.6.7-.6 1.2v2.1c0 .6.5 1 1 1h3.5c.6 0 1-.5 1-1v-1.5c1.2-.4 2.6-.6 3.9-.6s2.8.2 3.9.6V14c0 .6.5 1 1 1H21c.6 0 1-.5 1-1v-2.1c0-.5-.2-.9-.6-1.2C17.7 9 14.9 8 12 8z"
        transform="rotate(135 12 12)"
      />
    </svg>
  );
}

function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v5a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.9V21h2v-3.1A7 7 0 0 0 19 11h-2z" />
    </svg>
  );
}

function MicOffIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M19 11h-1.7c0 .58-.1 1.13-.27 1.64l1.27 1.27c.43-.9.7-1.88.7-2.91zM15 11.16V6a3 3 0 0 0-5.94-.6L15 11.16zM4.27 3 3 4.27l6.01 6.01V11a3 3 0 0 0 3 3c.22 0 .44-.03.65-.08l1.66 1.66c-.71.33-1.5.52-2.31.52a5 5 0 0 1-5-5H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c.91-.13 1.77-.45 2.55-.9L19.73 21 21 19.73 4.27 3z" />
    </svg>
  );
}

function SpeakerOnIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3 10v4c0 .55.45 1 1 1h3l3.29 3.29c.63.63 1.71.18 1.71-.71V6.41c0-.89-1.08-1.34-1.71-.71L7 9H4c-.55 0-1 .45-1 1zm13.5 2A4.5 4.5 0 0 0 14 7.97v8.05A4.5 4.5 0 0 0 16.5 12zM14 3.23v2.06A7.001 7.001 0 0 1 19 12c0 3.21-2.16 5.92-5 6.71v2.06c3.95-.84 7-4.36 7-8.77 0-4.4-3.05-7.93-7-8.77z" />
    </svg>
  );
}

function SpeakerOffIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M16.5 12A4.5 4.5 0 0 0 14 7.97v2.21l2.45 2.45c.03-.21.05-.42.05-.63zM19 12c0 .94-.2 1.82-.54 2.64l1.51 1.51A8.96 8.96 0 0 0 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3 3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.17v2.06a8.99 8.99 0 0 0 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4 9.91 6.09 12 8.18V4z" />
    </svg>
  );
}

export function CallPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { language, setLanguage } = useLanguage();
  const { sessionId, setSessionId } = useSessionStorage();

  const { setAssessment } = useChat(sessionId, language);
  const [pendingDisplayAssessment, setPendingDisplayAssessment] =
    useState<ChatAssessment | null>(null);
  const [displayAssessment, setDisplayAssessment] = useState<ChatAssessment | null>(null);
  const [callFinished, setCallFinished] = useState(false);

  const greeting = t('callGreeting');

  const voiceCall = useVoiceCall({
    sessionId,
    language,
    initialGreeting: greeting,
    onGreeting: (text) => {
      if (!sessionId) return;
      void api
        .createMessage(sessionId, {
          role: 'assistant',
          content: text,
          model_name: 'hotline-greeting-script',
        })
        .catch(() => undefined);
    },
    onAssessmentComplete: (payload) => {
      void (async () => {
        try {
          const departments = await api.listDepartments();
          const deptMap = new Map(
            departments.map((d) => [
              d.id,
              language === 'th' ? d.name_th ?? d.name_en : d.name_en,
            ]),
          );
          const next = toAssessment(payload, deptMap);
          setPendingDisplayAssessment(next);
        } catch {
          setPendingDisplayAssessment(toAssessment(payload, new Map()));
        }
      })();
    },
  });

  const callActive = voiceCall.state !== 'idle' && voiceCall.state !== 'error';
  const assessmentReceived = Boolean(
    pendingDisplayAssessment || displayAssessment || voiceCall.completedAssessment,
  );
  const assessmentReady = callFinished && Boolean(displayAssessment);
  const autoStartedRef = useRef(false);
  const [autoStartBlocked, setAutoStartBlocked] = useState(false);

  useEffect(() => {
    if (!sessionId) {
      navigate('/patient');
    }
  }, [sessionId, navigate]);

  useEffect(() => {
    if (!sessionId || !voiceCall.supported || autoStartedRef.current) return;
    autoStartedRef.current = true;
    void (async () => {
      try {
        await voiceCall.start();
      } catch {
        setAutoStartBlocked(true);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, voiceCall.supported]);

  useEffect(() => {
    return () => {
      void voiceCall.end();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // When the call auto-ends after assessment, mark the session complete.
  useEffect(() => {
    if (!sessionId || callFinished) return;
    if (voiceCall.state !== 'idle' || !voiceCall.completedAssessment) return;
    setCallFinished(true);
    void api.updateSession(sessionId, { status: 'completed' }).catch(() => undefined);
  }, [sessionId, callFinished, voiceCall.state, voiceCall.completedAssessment]);

  useEffect(() => {
    if (!callFinished || !pendingDisplayAssessment || displayAssessment) return;
    setDisplayAssessment(pendingDisplayAssessment);
    setAssessment(pendingDisplayAssessment);
  }, [callFinished, pendingDisplayAssessment, displayAssessment, setAssessment]);

  const statusLabel = useMemo(() => {
    if (assessmentReceived) {
      return callActive || voiceCall.autoEnding
        ? t('callStateAutoEnding')
        : t('callAssessmentCompleteTitle');
    }

    switch (voiceCall.state) {
      case 'starting':
        return t('callStateStarting');
      case 'greeting':
        return t('callStateGreeting');
      case 'listening':
        return voiceCall.muted ? t('callMuted') : t('callStateListening');
      case 'uploading':
        return t('callStateUploading');
      case 'thinking':
        return t('callStateThinking');
      case 'speaking':
        return t('callStateSpeaking');
      case 'error':
        return voiceCall.error ?? '';
      default:
        if (voiceCall.autoEnding) return t('callStateAutoEnding');
        if (callFinished) return t('callAssessmentCompleteTitle');
        return t('callEnded');
    }
  }, [
    assessmentReceived,
    callActive,
    voiceCall.state,
    voiceCall.error,
    voiceCall.autoEnding,
    voiceCall.muted,
    callFinished,
    t,
  ]);

  const handleManualStart = async () => {
    setAutoStartBlocked(false);
    await voiceCall.start();
  };

  const handleEndCall = async () => {
    await voiceCall.end();
    if (sessionId) {
      try {
        await api.updateSession(sessionId, { status: 'completed' });
      } catch {
        // best-effort — do not block UI
      }
      setSessionId(null);
    }
    navigate('/patient');
  };

  if (!sessionId) {
    return null;
  }

  if (!voiceCall.supported) {
    return (
      <Layout language={language} onLanguageChange={setLanguage}>
        <section className="call-page-fallback">
          <h1>{t('callNotSupported')}</h1>
          <p className="muted">{t('callPermissionHelp')}</p>
          <button type="button" className="primary-btn" onClick={() => navigate('/chat')}>
            {t('modeChatTitle')}
          </button>
        </section>
      </Layout>
    );
  }

  return (
    <Layout
      language={language}
      onLanguageChange={setLanguage}
      navTitle={t('callPageTitle')}
      showAdminLink={false}
    >
      <section className="call-page">
        <div className={`call-card ${assessmentReady ? 'assessment-ready' : ''}`}>
          <div className="call-header">
            <span className="call-status-pill">{t('callPageSubtitle')}</span>
            <h1>{t('callPageTitle')}</h1>
          </div>

          <div
            className={`call-orb ${
              assessmentReady ? 'call-orb-complete' : `call-orb-${voiceCall.state}`
            }`}
          >
            <div className="call-orb-ring" aria-hidden="true" />
            <div className="call-orb-ring delay" aria-hidden="true" />
            <div className="call-orb-core" aria-hidden="true">
              <PhoneIcon />
            </div>
          </div>

          <div className="call-status-block">
            <span className={`call-status-text state-${voiceCall.state}`}>
              {statusLabel || t('callTapToStart')}
            </span>
          </div>

          {(voiceCall.state === 'starting' || voiceCall.state === 'greeting') && !callFinished && (
            <div className="call-loading" role="status" aria-live="polite">
              <div className="call-loading-spinner" aria-hidden="true" />
              <div className="call-loading-text">
                <p className="call-loading-title">{t('callStateStarting')}</p>
                <p className="muted">{t('callPermissionHelp')}</p>
              </div>
            </div>
          )}

          {(voiceCall.lastTranscript || voiceCall.lastReply) && (
            <div className="call-captions">
              {voiceCall.lastTranscript && (
                <div className="caption caption-user">
                  <span className="caption-label">{t('lastYouSaid')}</span>
                  <p>"{voiceCall.lastTranscript}"</p>
                </div>
              )}
              {voiceCall.lastReply && (
                <div className="caption caption-assistant">
                  <span className="caption-label">{t('lastAssistantSaid')}</span>
                  <p>{voiceCall.lastReply}</p>
                </div>
              )}
            </div>
          )}

          {assessmentReady && (
            <div className="call-assessment-panel assessment-complete">
              <h2>{t('callAssessmentCompleteTitle')}</h2>
              <p className="muted">{t('callAssessmentCompleteSubtitle')}</p>
              {displayAssessment && <RecommendationCard assessment={displayAssessment} />}
              {displayAssessment && (
                <p className="muted call-session-id">
                  {t('sessionId')}: <code>{sessionId}</code>
                </p>
              )}
              {displayAssessment && (
                <PatientIdPassPopup
                  sessionId={sessionId}
                  language={language}
                  assessment={displayAssessment}
                  autoOpenKey={`${sessionId}-${displayAssessment.assistantMessageId ?? displayAssessment.severity?.level ?? 'assessment'}`}
                  triggerVariant="primary"
                />
              )}
              {callFinished && (
                <button
                  type="button"
                  className="secondary-btn call-home-btn"
                  onClick={() => {
                    setSessionId(null);
                    navigate('/patient');
                  }}
                >
                  {t('callBackHome')}
                </button>
              )}
            </div>
          )}

          <div className={`call-actions ${assessmentReady ? 'assessment-complete' : ''}`}>
            {!callActive && autoStartBlocked && !callFinished && !assessmentReady && (
              <button
                type="button"
                className="call-btn start"
                onClick={() => void handleManualStart()}
              >
                <span aria-hidden="true" className="call-btn-icon">{'\u260E'}</span>
                {t('callTapToStart')}
              </button>
            )}
            {callActive && (
              <>
                <button
                  type="button"
                  className={`call-btn mute call-btn-mute${voiceCall.muted ? ' is-muted' : ''}`}
                  onClick={() => {
                    if (voiceCall.muted) {
                      voiceCall.setMuted(false);
                    } else {
                      voiceCall.sendTurn();
                    }
                  }}
                  aria-pressed={voiceCall.muted}
                  disabled={assessmentReady}
                >
                  <span aria-hidden="true" className="call-btn-icon">
                    {voiceCall.muted ? <MicOffIcon /> : <MicIcon />}
                  </span>
                  {voiceCall.muted ? t('callUnmute') : t('callMute')}
                </button>
                <button
                  type="button"
                  className={`call-btn speaker call-btn-speaker${
                    voiceCall.speakerEnabled ? '' : ' is-off'
                  }`}
                  onClick={() => voiceCall.toggleSpeaker()}
                  aria-pressed={!voiceCall.speakerEnabled}
                  disabled={assessmentReady}
                >
                  <span aria-hidden="true" className="call-btn-icon">
                    {voiceCall.speakerEnabled ? <SpeakerOnIcon /> : <SpeakerOffIcon />}
                  </span>
                  {voiceCall.speakerEnabled ? t('callSpeakerOff') : t('callSpeakerOn')}
                </button>
              </>
            )}
            {!callFinished && (
              <button
                type="button"
                className="call-btn end call-btn-hangup"
                onClick={() => void handleEndCall()}
                disabled={assessmentReady}
              >
                <span aria-hidden="true" className="call-btn-icon">
                  <HangUpIcon />
                </span>
                {t('endCall')}
              </button>
            )}
          </div>

          {voiceCall.error && <p className="error-text call-error">{voiceCall.error}</p>}
        </div>
      </section>
    </Layout>
  );
}
