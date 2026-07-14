import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { AnimatePresence, motion } from 'framer-motion';
import { Check, PhoneOff, Sparkles } from 'lucide-react';
import type { AppLanguage } from '../../i18n/resources';
import type { VoiceCallState } from '../../hooks/useVoiceCall';
import { AiOrb } from './AiOrb';
import { MeasurementCard } from '../MeasurementCard';

interface ReplyOption {
  id: string;
  label: string;
}

interface ConversationStageProps {
  language: AppLanguage;
  state: VoiceCallState;
  lastReply: string;
  lastTranscript: string;
  replyOptions: ReplyOption[];
  onTapReply: (label: string) => void;
  /** Signal end-of-turn ("I'm finished speaking") → useVoiceCall.sendTurn. */
  onDone: () => void;
  onEnd: () => void;
  measurementVital: string | null;
  onMeasurementSubmit: (continuationText: string) => void;
  /**
   * Future lip-synced avatar. Render the avatar component here (video /
   * canvas / WebGL — children auto-fill the tile via CSS) and it replaces
   * the orb placeholder inside the reserved stage with no layout changes.
   * The stage also carries a stable DOM id (#kiosk-avatar-slot) for
   * imperative mounting. Drive sync from the same `state` prop
   * (listening / thinking / speaking) that animates the orb today.
   */
  avatar?: ReactNode;
}

/**
 * Live AI symptom conversation, laid out around the assistant's "presence":
 * a portrait video-call-style avatar stage (orb placeholder today, synced
 * avatar later) beside the captions, answer chips and turn controls.
 */
export function ConversationStage({
  language,
  state,
  lastReply,
  lastTranscript,
  replyOptions,
  onTapReply,
  onDone,
  onEnd,
  measurementVital,
  onMeasurementSubmit,
  avatar,
}: ConversationStageProps) {
  const { t } = useTranslation();

  const isListening = state === 'listening';
  const isSpeaking = state === 'speaking';
  const busy =
    state === 'thinking' || state === 'uploading' || state === 'starting' || state === 'greeting';

  // Label + semantic chip color per engine state: green = mic live,
  // amber = processing, blue = assistant speaking, gray = connecting.
  const [stateLabel, chipState] = ((): [string, string] => {
    switch (state) {
      case 'starting':
      case 'greeting':
        return [t('kioskConvConnecting'), 'connecting'];
      case 'listening':
        return [t('kioskConvListening'), 'listening'];
      case 'uploading':
      case 'thinking':
        return [t('kioskConvThinking'), 'thinking'];
      case 'speaking':
        return [t('kioskConvSpeaking'), 'speaking'];
      default:
        return ['', 'connecting'];
    }
  })();

  const showAnswers = !measurementVital && replyOptions.length > 0;

  const guidance = measurementVital
    ? ''
    : showAnswers
      ? t('kioskConvTapAnswer')
      : isListening
        ? t('kioskConvSpeakNow')
        : '';

  const doneLabel = isSpeaking
    ? t('kioskConvAiSpeaking')
    : busy
      ? t('kioskConvWait')
      : t('kioskConvDone');

  return (
    <div className="k-conv k-conv--avatar">
      {/* The assistant's visual presence: reserved avatar tile + live state. */}
      <div className="k-avatar-col">
        <div className="k-avatar-stage" id="kiosk-avatar-slot">
          {avatar ?? <AiOrb state={state} size={124} />}
        </div>
        {stateLabel && (
          <span className={`k-status-chip k-status-chip--${chipState}`}>
            <span className="k-status-dot" aria-hidden="true" />
            {stateLabel}
          </span>
        )}
      </div>

      <div className="k-conv-main">
        {/* Assistant speech card */}
        <div className="k-speech">
          <div className="k-speech-label">
            <Sparkles size={16} aria-hidden="true" />
            {t('kioskAssistantLabel')}
          </div>
          <AnimatePresence mode="wait">
            <motion.p
              key={lastReply || stateLabel}
              className="k-speech-text"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.3 }}
            >
              {lastReply || '…'}
            </motion.p>
          </AnimatePresence>
        </div>

        {lastTranscript && (
          <p className="k-user-echo">
            <b>{t('kioskYouLabel')}:</b>
            {lastTranscript}
          </p>
        )}

        {guidance && <p className="k-guidance">{guidance}</p>}

        {/* Measurement request takes over the middle when present. */}
        {measurementVital ? (
          <div style={{ width: '100%', maxWidth: 560 }}>
            <MeasurementCard
              vital={measurementVital}
              language={language}
              onSubmit={onMeasurementSubmit}
            />
          </div>
        ) : (
          <AnimatePresence>
            {showAnswers && (
              <motion.div
                className="k-answers"
                initial="hidden"
                animate="show"
                exit={{ opacity: 0 }}
                variants={{ show: { transition: { staggerChildren: 0.06 } } }}
              >
                {replyOptions.map((opt) => (
                  <motion.button
                    key={opt.id}
                    type="button"
                    className="k-chip"
                    onClick={() => onTapReply(opt.label)}
                    variants={{
                      hidden: { opacity: 0, scale: 0.9, y: 14 },
                      show: { opacity: 1, scale: 1, y: 0 },
                    }}
                    transition={{ type: 'spring', stiffness: 340, damping: 24 }}
                    whileTap={{ scale: 0.96 }}
                  >
                    {opt.label}
                  </motion.button>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        )}

        {/* Bottom bar: XL turn-end + labeled end-conversation */}
        {!measurementVital && (
          <div className="k-conv-bar">
            <motion.button
              type="button"
              className="k-btn success xl"
              onClick={onDone}
              disabled={!isListening}
              whileTap={isListening ? { scale: 0.97 } : undefined}
              animate={
                isListening
                  ? {
                      boxShadow: [
                        '0 10px 24px -10px rgba(30,138,90,0.5), 0 0 0 0 rgba(30,138,90,0.35)',
                        '0 10px 24px -10px rgba(30,138,90,0.5), 0 0 0 16px rgba(30,138,90,0)',
                      ],
                    }
                  : // Clear the inline shadow so the flat gray :disabled style shows.
                    { boxShadow: '0 0 0 0 rgba(0,0,0,0)' }
              }
              transition={isListening ? { duration: 1.8, repeat: Infinity } : {}}
            >
              <Check size={28} strokeWidth={2.6} aria-hidden="true" />
              {doneLabel}
            </motion.button>

            <button type="button" className="k-btn danger-ghost" onClick={onEnd}>
              <PhoneOff size={22} aria-hidden="true" />
              {t('kioskEndConversation')}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
