import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import { Layout } from '../components/Layout';
import { MessageBubble, TypingIndicator } from '../components/MessageBubble';
import { PatientIdPassPopup } from '../components/PatientIdPass';
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
    streamingTurn,
    loadMessages,
    sendMessage,
    sendMessageStream,
  } = useChat(sessionId, language);

  const [mapAutoOpen, setMapAutoOpen] = useState(false);
  const speech = useSpeechRecognition(language);
  const synthesis = useSpeechSynthesis(language);
  const frontdeskMode = (import.meta.env.VITE_FRONTDESK_MODE ?? 'false') === 'true';
  const assessmentComplete = Boolean(
    assessment?.severity?.level && 
    assessment.severity.level !== 'unknown' && 
    assessment.contact?.contact_preference_recorded && 
    !assessment.contact?.needs_followup
  );

  const voiceCall = useVoiceCall({
    sessionId,
    language,
    onTranscript: async (transcript) => {
      if (assessmentComplete) return null;
      // The voice-call legacy path still uses non-streaming chat —
      // streaming only makes sense for the typed/text input. Voice
      // input goes through Gemini Live's own audio response instead.
      const result = await sendMessage(transcript, 'voice');
      return result?.response.reply ?? null;
    },
  });
  const callActive = voiceCall.state !== 'idle' && voiceCall.state !== 'error';
  const composerDisabled = isSending || callActive || assessmentComplete;

  useEffect(() => {
    if (frontdeskMode && synthesis.supported) {
      synthesis.setEnabled(true);
    }
  }, [frontdeskMode, synthesis]);

  useEffect(() => {
    return () => {
      void voiceCall.end();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!sessionId) {
      navigate('/patient');
      return;
    }
    void loadMessages();
  }, [sessionId, navigate, loadMessages]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isSending, streamingTurn?.assistantText, streamingTurn?.done]);

  const handleSend = async (overrideText?: string, inputMode: 'voice' | 'text' = 'text') => {
    const text = (overrideText ?? input).trim();
    if (!text || assessmentComplete) return;

    if (!overrideText) {
      setInput('');
    }

    // Voice-input turns route through the existing non-streaming path
    // because the live voice call has its own audio response stream
    // and we don't want to TTS the typed reply on top of that.
    if (inputMode === 'voice' || callActive) {
      const result = await sendMessage(text, inputMode);
      if (result?.response.reply && !callActive) {
        void synthesis.speak(result.response.reply);
      }
      return;
    }

    // Streaming text turn: the user message renders optimistically as
    // soon as we kick off, the assistant bubble fills in via delta
    // events, and TTS — when enabled — plays sentence by sentence.
    synthesis.stop();
    await sendMessageStream(text, 'text', {
      onDelta: (chunk) => {
        // Sentence-boundary TTS so audio plays alongside the typewriter
        // text. When the speaker is off this is a no-op inside the hook.
        synthesis.speakStreamChunk(chunk);
      },
      onReset: () => {
        // The deltas we already enqueued for TTS were inner-LLM
        // reasoning (e.g. the orchestrator's "Hello, I can help"
        // before it transfers to TriageAgent). Stop any in-flight
        // playback + queued audio so the user doesn't hear the
        // discarded thinking on top of the real reply.
        synthesis.stop();
      },
      onComplete: () => {
        synthesis.flushStream();
      },
    });
  };

  const handleToggleCall = () => {
    if (callActive) {
      void voiceCall.end();
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
    if (assessmentComplete) return;
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
      navigate('/patient');
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

        {assessmentComplete && assessment?.severity && assessment.severity.level !== 'unknown' && (
          <div className={`triage-panel severity-${assessment.severity.level}`}>
            <div>
              <strong>{t('triageStatus')}:</strong>{' '}
              {t(`severity_${assessment.severity.level}`)}
              {assessment.severity.explanation ? ` - ${assessment.severity.explanation}` : ''}
            </div>
          </div>
        )}

        {assessmentComplete && assessment && (
          <div className="chat-assessment-summary">
            <RecommendationCard assessment={assessment} autoOpenMap={mapAutoOpen} />
            <p className="muted call-session-id">
              {t('sessionId')}: <code>{sessionId}</code>
            </p>
            <div style={{ marginTop: '16px' }}>
              <PatientIdPassPopup
                sessionId={sessionId}
                language={language}
                assessment={assessment}
                autoOpenKey={`${sessionId}-${assessment.assistantMessageId ?? assessment.severity?.level ?? 'assessment'}`}
                onClose={() => setMapAutoOpen(true)}
                triggerVariant="primary"
              />
            </div>
          </div>
        )}

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
          {!isLoading && messages.length === 0 && !streamingTurn && (
            <p className="muted">{t('noMessages')}</p>
          )}
          {messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}
          {/* Live streaming assistant bubble. Rendered ONLY while a
              turn is in flight — once the ``complete`` event arrives,
              the assistant message is appended to ``messages`` and
              ``streamingTurn`` is cleared so this collapses cleanly
              without a flicker. The empty-text case still shows the
              bubble (with a typing indicator inside) so the user has
              immediate feedback that their message was received. */}
          {streamingTurn && !streamingTurn.done && (
            <div className="message-bubble assistant streaming">
              <div className="message-meta">
                <span className="message-role">{t('assistant')}</span>
              </div>
              {streamingTurn.assistantText ? (
                <p className="message-content">
                  {streamingTurn.assistantText}
                  <span className="streaming-cursor" aria-hidden="true">▍</span>
                </p>
              ) : (
                <TypingIndicator visible={true} />
              )}
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {error && <p className="error-text">{error}</p>}

        {speech.isListening && (
          <p className="listening-label">{t('listening')}</p>
        )}

        <div className={`chat-input-row ${assessmentComplete ? 'assessment-complete' : ''}`}>
          <VoiceControls
            voiceEnabled={speech.enabled}
            voiceSupported={speech.supported && !callActive && !assessmentComplete}
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
            placeholder={
              assessmentComplete
                ? t('assessmentCompleteInput')
                : callActive
                  ? t('callHintActive')
                  : t('typeMessage')
            }
            disabled={composerDisabled}
            aria-label={t('typeMessage')}
          />
          <button
            type="button"
            className="primary-btn"
            onClick={() => void handleSend()}
            disabled={composerDisabled || !input.trim()}
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
