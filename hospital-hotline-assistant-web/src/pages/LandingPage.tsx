import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import { Layout } from '../components/Layout';
import { useLanguage, useSessionStorage } from '../hooks/useSession';

function HotlineIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.8-.4 1.2-.2 1 .4 2 .7 3 .9.4.1.7.4.7.9V20c0 .6-.4 1-1 1C10.1 21 3 13.9 3 5c0-.6.4-1 1-1h3.5c.5 0 .9.3 1 .8.2 1 .5 2 1 3 .1.4 0 .9-.3 1.2L6.6 10.8z" />
    </svg>
  );
}

export function LandingPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { language, setLanguage } = useLanguage();
  const { setSessionId } = useSessionStorage();
  const [isStarting, setIsStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleStart = async () => {
    setIsStarting(true);
    setError(null);
    try {
      const session = await api.createSession({
        language,
        user_agent: navigator.userAgent,
      });
      setSessionId(session.id);
      navigate('/chat');
    } catch (err) {
      setError(err instanceof Error ? err.message : t('error'));
    } finally {
      setIsStarting(false);
    }
  };

  return (
    <Layout language={language} onLanguageChange={setLanguage}>
      <section className="landing">
        <div className="landing-card">
          <span className="landing-badge">{t('landingBadge')}</span>
          <div className="landing-icon-wrap">
            <HotlineIcon />
          </div>
          <h1>{t('appName')}</h1>
          <p className="landing-tagline">{t('tagline')}</p>
          {error && <p className="error-text">{error}</p>}
          <button
            type="button"
            className="primary-btn large-btn"
            onClick={() => void handleStart()}
            disabled={isStarting}
          >
            {isStarting ? t('loading') : t('startHotline')}
          </button>
        </div>
      </section>
    </Layout>
  );
}
