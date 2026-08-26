import { useTranslation } from 'react-i18next';
import type { MessageOut } from '../api/types';

interface MessageBubbleProps {
  message: MessageOut;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const { t } = useTranslation();
  const roleLabel =
    message.role === 'user'
      ? t('user')
      : message.role === 'assistant'
        ? t('assistant')
        : t('system');
  const modeLabel =
    message.input_mode === 'voice'
      ? t('inputModeVoice')
      : message.input_mode === 'button'
        ? t('inputModeButton')
        : message.input_mode === 'text'
          ? t('inputModeText')
          : null;

  return (
    <div className={`message-bubble ${message.role}`}>
      <div className="message-meta">
        <span className="message-role">{roleLabel}</span>
      </div>
      {/* The input mode trails the words rather than sitting beside the name:
          it says how this utterance was produced, which qualifies the words,
          not who said them. Beside the name it also outweighed it — a bordered
          pill against plain text — and the speaker is what gets scanned. */}
      <p className="message-content">
        {message.content}
        {modeLabel && (
          <span className={`message-mode message-mode-${message.input_mode}`}>
            {modeLabel}
          </span>
        )}
      </p>
    </div>
  );
}

interface TypingIndicatorProps {
  visible: boolean;
}

export function TypingIndicator({ visible }: TypingIndicatorProps) {
  const { t } = useTranslation();
  if (!visible) return null;

  return (
    <div className="typing-indicator" aria-live="polite">
      <span className="typing-dots">
        <span />
        <span />
        <span />
      </span>
      {t('typing')}
    </div>
  );
}
