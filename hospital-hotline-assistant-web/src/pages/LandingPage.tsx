import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import { Layout } from '../components/Layout';
import { HospitalMapViewer } from '../components/HospitalMapViewer';
import { useLanguage, useSessionStorage, setStoredPatientName } from '../hooks/useSession';
import { prewarmVoiceCall } from '../hooks/voicePrewarm';

function PhoneIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.8-.4 1.2-.2 1 .4 2 .7 3 .9.4.1.7.4.7.9V20c0 .6-.4 1-1 1C10.1 21 3 13.9 3 5c0-.6.4-1 1-1h3.5c.5 0 .9.3 1 .8.2 1 .5 2 1 3 .1.4 0 .9-.3 1.2L6.6 10.8z" />
    </svg>
  );
}

function ChatIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 4h16c1.1 0 2 .9 2 2v10c0 1.1-.9 2-2 2H7l-4 4V6c0-1.1.9-2 2-2zm2 4v2h12V8H6zm0 4v2h9v-2H6z" />
    </svg>
  );
}

function MapIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M20.5 3l-.16.03L15 5.1 9 3 3.36 4.9c-.21.07-.36.25-.36.48V20.5c0 .28.22.5.5.5l.16-.03L9 18.9l6 2.1 5.64-1.9c.21-.07.36-.25.36-.48V3.5c0-.28-.22-.5-.5-.5zM15 19l-6-2.11V5l6 2.11V19z" />
    </svg>
  );
}


export function LandingPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { language, setLanguage } = useLanguage();
  const { setSessionId } = useSessionStorage();
  const [startingMode, setStartingMode] = useState<'call' | 'chat' | null>(null);
  const [showMap, setShowMap] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [visitId, setVisitId] = useState('');

  const startSession = async (mode: 'call' | 'chat') => {
    setStartingMode(mode);
    setError(null);

    // If a voice call is imminent, kick off mic-permission + playback
    // context warmup in parallel with session creation. The browser's
    // mic permission prompt is by far the slowest single step on a cold
    // call (200 ms - 2 s+); doing it here means the prompt is already
    // resolved by the time the user reaches the call page, and the
    // first `getUserMedia` inside `useVoiceCall.start()` returns
    // instantly. We do NOT await this — session creation runs in
    // parallel so the overall click-to-call-page time is shaped by
    // whichever finishes last (typically the permission prompt the
    // first time, the session POST every other time).
    if (mode === 'call') {
      void prewarmVoiceCall();
    }

    try {
      const session = await api.createSession({
        language,
        user_agent: navigator.userAgent,
      });
      setSessionId(session.id);
      setStoredPatientName(null);
      // Link the hospital visit if the patient typed/scanned a visit ID at
      // the booth. Best-effort: an unknown or failed link never blocks the
      // patient — they continue anonymously.
      const trimmedVisit = visitId.trim();
      if (trimmedVisit) {
        try {
          const linked = await api.linkVisit(session.id, trimmedVisit);
          if (linked.patient_name) {
            setStoredPatientName(linked.patient_name);
          }
        } catch {
          /* continue anonymously */
        }
      }
      navigate(mode === 'call' ? '/call' : '/chat');
    } catch (err) {
      setError(err instanceof Error ? err.message : t('error'));
      setStartingMode(null);
    }
  };

  return (
    <Layout language={language} onLanguageChange={setLanguage}>
      <section className="landing">
        <div className="landing-card landing-card-wide">
          <span className="landing-badge">{t('landingBadge')}</span>
          <h1>{t('landingChooseTitle')}</h1>
          <p className="landing-tagline">{t('landingChooseTagline')}</p>
          {error && <p className="error-text">{error}</p>}

          <div className="visit-id-field">
            <label htmlFor="visit-id-input" className="visit-id-label">
              {t('visitIdLabel')}
            </label>
            <input
              id="visit-id-input"
              type="text"
              inputMode="numeric"
              autoComplete="off"
              className="visit-id-input"
              placeholder={t('visitIdPlaceholder')}
              value={visitId}
              onChange={(e) => setVisitId(e.target.value)}
              disabled={startingMode !== null}
            />
            <span className="visit-id-hint">{t('visitIdHint')}</span>
          </div>

          <div className="mode-grid">
            <button
              type="button"
              className="mode-tile mode-tile-call"
              onClick={() => void startSession('call')}
              disabled={startingMode !== null}
            >
              <span className="mode-icon mode-icon-call">
                <PhoneIcon />
              </span>
              <span className="mode-title">{t('modeCallTitle')}</span>
              <span className="mode-subtitle">{t('modeCallSubtitle')}</span>
              {startingMode === 'call' && (
                <span className="mode-loading">{t('loading')}</span>
              )}
            </button>

            <button
              type="button"
              className="mode-tile mode-tile-chat"
              onClick={() => void startSession('chat')}
              disabled={startingMode !== null}
            >
              <span className="mode-icon mode-icon-chat">
                <ChatIcon />
              </span>
              <span className="mode-title">{t('modeChatTitle')}</span>
              <span className="mode-subtitle">{t('modeChatSubtitle')}</span>
              {startingMode === 'chat' && (
                <span className="mode-loading">{t('loading')}</span>
              )}
            </button>

            <button
              type="button"
              className={`mode-tile mode-tile-map${showMap ? ' active' : ''}`}
              onClick={() => setShowMap((v) => !v)}
              disabled={startingMode !== null}
            >
              <span className="mode-icon mode-icon-map">
                <MapIcon />
              </span>
              <span className="mode-title">{t('modeMapTitle')}</span>
              <span className="mode-subtitle">{t('modeMapSubtitle')}</span>
            </button>
          </div>

          {showMap && <HospitalMapViewer />}

          <p className="landing-disclaimer muted">{t('disclaimer')}</p>
        </div>
      </section>
    </Layout>
  );
}
