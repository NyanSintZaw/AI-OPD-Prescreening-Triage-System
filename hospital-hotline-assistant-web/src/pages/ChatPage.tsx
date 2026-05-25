import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import { EmergencyBanner } from '../components/EmergencyBanner';
import { Layout } from '../components/Layout';
import { MessageBubble, TypingIndicator } from '../components/MessageBubble';
import { RecommendationCard } from '../components/RecommendationCard';
import { VoiceControls } from '../components/VoiceControls';
import { useChat } from '../hooks/useChat';
import { useLanguage, useSessionStorage } from '../hooks/useSession';
import { useSpeechRecognition, useSpeechSynthesis } from '../hooks/useSpeech';

export function ChatPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { language, setLanguage } = useLanguage();
  const { sessionId, setSessionId } = useSessionStorage();
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const {
    messages,
    isLoading,
    isSending,
    error,
    assessment,
    loadMessages,
    sendMessage,
  } = useChat(sessionId, language);

  const speech = useSpeechRecognition(language);
  const synthesis = useSpeechSynthesis(language);
  const frontdeskMode = (import.meta.env.VITE_FRONTDESK_MODE ?? 'false') === 'true';

  useEffect(() => {
    if (frontdeskMode && synthesis.supported) {
      synthesis.setEnabled(true);
    }
  }, [frontdeskMode, synthesis]);

  useEffect(() => {
    if (!sessionId) {
      navigate('/');
      return;
    }
    void loadMessages();
  }, [sessionId, navigate, loadMessages]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isSending]);

  useEffect(() => {
    if (speech.transcript && !speech.isListening) {
      setInput(speech.transcript);
      speech.clearTranscript();
    }
  }, [speech.transcript, speech.isListening, speech]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text) return;

    setInput('');
    const result = await sendMessage(text, speech.enabled && speech.supported ? 'voice' : 'text');
    if (result?.aiResponse.reply) {
      synthesis.speak(result.aiResponse.reply);
    }
  };

  const handleMicClick = () => {
    if (speech.isListening) {
      speech.stopListening();
    } else {
      speech.startListening();
    }
  };

  const handleReset = async () => {
    if (!sessionId) return;
    try {
      await api.updateSession(sessionId, { status: 'reset' });
      const session = await api.createSession({
        language,
        user_agent: navigator.userAgent,
      });
      setSessionId(session.id);
      setInput('');
    } catch (err) {
      console.error(err);
    }
  };

  const handleEndSession = async () => {
    if (!sessionId) return;
    try {
      await api.updateSession(sessionId, { status: 'completed' });
      setSessionId(null);
      navigate('/');
    } catch (err) {
      console.error(err);
    }
  };

  if (!sessionId) {
    return null;
  }

  return (
    <Layout language={language} onLanguageChange={setLanguage}>
      <section className="chat-page">
        <div className="chat-header">
          <h1>{t('chatTitle')}</h1>
          <div className="chat-actions">
            <button type="button" className="secondary-btn" onClick={() => void handleReset()}>
              {t('reset')}
            </button>
            <button type="button" className="secondary-btn" onClick={() => void handleEndSession()}>
              {t('endSession')}
            </button>
          </div>
        </div>

        {assessment?.severity && (
          <div className={`triage-panel severity-${assessment.severity.level}`}>
            <div>
              <strong>{t('triageStatus')}:</strong>{' '}
              {t(`severity_${assessment.severity.level}`)}
              {assessment.severity.explanation ? ` - ${assessment.severity.explanation}` : ''}
            </div>
            {assessment.alertSent && (
              <div className="triage-alert-note">{t('humanAlertSent')}</div>
            )}
          </div>
        )}

        {assessment?.emergency && (
          <EmergencyBanner
            message={assessment.emergency.alertMessage}
            ctaLabel={t('callStaffNow')}
            onCtaClick={() => {
              window.alert(t('callStaffInstruction'));
            }}
          />
        )}

        {assessment && <RecommendationCard assessment={assessment} />}

        {assessment?.followUpQuestion && (
          <div className="follow-up-card">
            <strong>{t('followUpQuestion')}</strong>
            <p>{assessment.followUpQuestion}</p>
            {assessment.followUpReason && <p className="muted">{assessment.followUpReason}</p>}
          </div>
        )}

        <div className="quick-prompts">
          <button
            type="button"
            className="quick-prompt-btn"
            onClick={() => setInput(t('quickPromptChestPain'))}
          >
            {t('quickPromptChestPain')}
          </button>
          <button
            type="button"
            className="quick-prompt-btn"
            onClick={() => setInput(t('quickPromptBreathing'))}
          >
            {t('quickPromptBreathing')}
          </button>
          <button
            type="button"
            className="quick-prompt-btn"
            onClick={() => setInput(t('quickPromptBleeding'))}
          >
            {t('quickPromptBleeding')}
          </button>
        </div>

        <div className="chat-messages">
          {isLoading && <p className="muted">{t('loading')}</p>}
          {!isLoading && messages.length === 0 && (
            <p className="muted">{t('noMessages')}</p>
          )}
          {messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}
          <TypingIndicator visible={isSending} />
          <div ref={messagesEndRef} />
        </div>

        {error && <p className="error-text">{error}</p>}

        {speech.isListening && (
          <p className="listening-label">{t('listening')}</p>
        )}

        <div className="chat-input-row">
          <VoiceControls
            voiceEnabled={speech.enabled}
            voiceSupported={speech.supported}
            isListening={speech.isListening}
            speakerEnabled={synthesis.enabled}
            speakerSupported={synthesis.supported}
            onMicClick={handleMicClick}
            onSpeakerToggle={synthesis.toggle}
          />
          <input
            type="text"
            className="chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                void handleSend();
              }
            }}
            placeholder={t('typeMessage')}
            disabled={isSending}
            aria-label={t('typeMessage')}
          />
          <button
            type="button"
            className="primary-btn"
            onClick={() => void handleSend()}
            disabled={isSending || !input.trim()}
          >
            {t('send')}
          </button>
        </div>
      </section>
    </Layout>
  );
}
