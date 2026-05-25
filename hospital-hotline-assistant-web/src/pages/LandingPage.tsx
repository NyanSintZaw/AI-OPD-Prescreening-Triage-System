import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import { Layout } from '../components/Layout';
import { useLanguage, useSessionStorage } from '../hooks/useSession';

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

export function LandingPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { language, setLanguage } = useLanguage();
  const { setSessionId } = useSessionStorage();
  const [startingMode, setStartingMode] = useState<'call' | 'chat' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const startSession = async (mode: 'call' | 'chat') => {
    setStartingMode(mode);
    setError(null);
    try {
      const session = await api.createSession({
        language,
        user_agent: navigator.userAgent,
      });
      setSessionId(session.id);
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
          </div>

          <p className="landing-disclaimer muted">{t('disclaimer')}</p>
        </div>
      </section>
    </Layout>
  );
}
