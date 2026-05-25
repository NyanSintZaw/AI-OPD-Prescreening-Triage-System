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

  return (
    <div className={`message-bubble ${message.role}`}>
      <div className="message-meta">
        <span className="message-role">{roleLabel}</span>
        {message.input_mode && (
          <span className="message-mode">{message.input_mode}</span>
        )}
      </div>
      <p className="message-content">{message.content}</p>
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
