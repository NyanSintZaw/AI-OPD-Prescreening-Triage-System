import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { motion } from 'framer-motion';
import { HandHeart } from '@phosphor-icons/react';

interface ConfirmNameStepProps {
  patientName: string;
  busy?: boolean;
  unclear?: boolean;
  onConfirm: (payload: { confirmed?: boolean; text?: string }) => void;
}

/**
 * "Is this you, {name}?" — Yes/No buttons plus a free-text field for
 * natural-language answers (ใช่ / ไม่ใช่ / that's not me, …).
 */
export function ConfirmNameStep({
  patientName,
  busy = false,
  unclear = false,
  onConfirm,
}: ConfirmNameStepProps) {
  const { t } = useTranslation();
  const [text, setText] = useState('');

  const submitText = () => {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    onConfirm({ text: trimmed });
  };

  return (
    <motion.div
      className="k-hello"
      initial={{ opacity: 0, scale: 0.94 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
      style={{ width: '100%', maxWidth: 560, margin: '0 auto' }}
    >
      <motion.span
        className="k-hello-badge"
        initial={{ scale: 0.6, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: 'spring', stiffness: 280, damping: 18, delay: 0.1 }}
      >
        <HandHeart size={52} weight="duotone" aria-hidden="true" />
      </motion.span>
      <h2 className="k-hello-name">{t('kioskConfirmNameTitle', { name: patientName })}</h2>
      <p className="k-hello-lead">{t('kioskConfirmNameLead')}</p>

      <div
        style={{
          display: 'flex',
          gap: 12,
          justifyContent: 'center',
          flexWrap: 'wrap',
          marginTop: 8,
          width: '100%',
        }}
      >
        <button
          type="button"
          className="k-btn primary xl"
          disabled={busy}
          onClick={() => onConfirm({ confirmed: true })}
          style={{ minWidth: 140 }}
        >
          {t('kioskConfirmNameYes')}
        </button>
        <button
          type="button"
          className="k-btn secondary xl"
          disabled={busy}
          onClick={() => onConfirm({ confirmed: false })}
          style={{ minWidth: 140 }}
        >
          {t('kioskConfirmNameNo')}
        </button>
      </div>

      <div style={{ width: '100%', marginTop: 20 }}>
        <label className="k-method-hint" htmlFor="kiosk-confirm-name-text">
          {t('kioskConfirmNameOrType')}
        </label>
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <input
            id="kiosk-confirm-name-text"
            type="text"
            value={text}
            disabled={busy}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submitText();
            }}
            placeholder={t('kioskConfirmNamePlaceholder')}
            className="k-display"
            style={{
              flex: 1,
              fontSize: 18,
              textAlign: 'left',
              padding: '12px 16px',
              minHeight: 48,
            }}
            autoComplete="off"
          />
          <button
            type="button"
            className="k-btn primary"
            disabled={busy || !text.trim()}
            onClick={submitText}
          >
            {t('kioskConfirmNameSend')}
          </button>
        </div>
        {unclear && !busy && (
          <p className="k-error" style={{ marginTop: 10 }}>
            {t('kioskConfirmNameUnclear')}
          </p>
        )}
      </div>
    </motion.div>
  );
}
