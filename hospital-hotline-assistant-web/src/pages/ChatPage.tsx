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
import { useVoiceCall } from '../hooks/useVoiceCall';

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

  const voiceCall = useVoiceCall({
    language,
    onTranscript: async (transcript) => {
      const result = await sendMessage(transcript, 'voice');
      return result?.response.reply ?? null;
    },
  });
  const callActive = voiceCall.state !== 'idle' && voiceCall.state !== 'error';

  useEffect(() => {
    if (frontdeskMode && synthesis.supported) {
      synthesis.setEnabled(true);
    }
  }, [frontdeskMode, synthesis]);

  useEffect(() => {
    return () => {
      voiceCall.end();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  const handleSend = async (overrideText?: string, inputMode: 'voice' | 'text' = 'text') => {
    const text = (overrideText ?? input).trim();
    if (!text) return;

    if (!overrideText) {
      setInput('');
    }
    const result = await sendMessage(text, inputMode);
    if (result?.response.reply && !callActive) {
      void synthesis.speak(result.response.reply);
    }
  };

  const handleToggleCall = () => {
    if (callActive) {
      voiceCall.end();
    } else {
      synthesis.stop();
      void voiceCall.start();
    }
  };

  const callStatusLabel = (() => {
    switch (voiceCall.state) {
      case 'starting':
        return t('callStateStarting');
      case 'listening':
        return t('callStateListening');
      case 'uploading':
        return t('callStateUploading');
      case 'thinking':
        return t('callStateThinking');
      case 'speaking':
        return t('callStateSpeaking');
      default:
        return '';
    }
  })();

  useEffect(() => {
    if (speech.transcript && !speech.isListening) {
      const transcript = speech.transcript;
      speech.clearTranscript();
      if (frontdeskMode) {
        void handleSend(transcript, 'voice');
      } else {
        setInput(transcript);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [speech.transcript, speech.isListening]);

  const handleMicClick = () => {
    if (speech.isListening) {
      speech.stopListening();
    } else {
      void speech.startListening();
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

        {voiceCall.supported ? (
          <div className={`voice-call-bar ${callActive ? 'active' : ''}`}>
            <div className="voice-call-bar-main">
              <button
                type="button"
                className={callActive ? 'call-btn end' : 'call-btn start'}
                onClick={handleToggleCall}
                disabled={voiceCall.state === 'starting'}
              >
                <span aria-hidden="true" className="call-btn-icon">
                  {callActive ? '\u2715' : '\u260E'}
                </span>
                {callActive ? t('endCall') : t('startCall')}
              </button>
              <div className="voice-call-status">
                {callActive ? (
                  <>
                    <span
                      className={`call-status-indicator state-${voiceCall.state}`}
                      aria-hidden="true"
                    />
                    <span className="call-status-text">{callStatusLabel}</span>
                  </>
                ) : (
                  <span className="muted">{t('callHintTap')}</span>
                )}
              </div>
            </div>
            {callActive && voiceCall.lastTranscript && (
              <p className="call-transcript">"{voiceCall.lastTranscript}"</p>
            )}
            {voiceCall.error && <p className="error-text">{voiceCall.error}</p>}
          </div>
        ) : null}

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
            voiceSupported={speech.supported && !callActive}
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
            placeholder={callActive ? t('callHintActive') : t('typeMessage')}
            disabled={isSending || callActive}
            aria-label={t('typeMessage')}
          />
          <button
            type="button"
            className="primary-btn"
            onClick={() => void handleSend()}
            disabled={isSending || !input.trim() || callActive}
          >
            {t('send')}
          </button>
        </div>

        {speech.error && <p className="error-text">{speech.error}</p>}
        {synthesis.error && <p className="error-text">{synthesis.error}</p>}
      </section>
    </Layout>
  );
}
