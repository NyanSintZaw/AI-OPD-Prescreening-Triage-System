import { motion } from 'framer-motion';
import { HandTap, Translate, X } from '@phosphor-icons/react';
import type { AppLanguage } from '../../i18n/resources';

interface LanguageSelectProps {
  onSelect: (lang: AppLanguage) => void;
  /** Disables the cards while the session is being created. */
  busy: boolean;
  /** Back to the home screen — rendered below the cards (bilingual label). */
  onExit: () => void;
  /** True when the last session-creation attempt failed — tapping a card retries. */
  error?: boolean;
}

/** Thai tricolour — official stripe ratio 1:1:2:1:1. */
function ThaiFlag() {
  return (
    <svg viewBox="0 0 90 60" role="img" aria-label="ธงชาติไทย">
      <rect width="90" height="60" fill="#A51931" />
      <rect y="10" width="90" height="40" fill="#F4F5F8" />
      <rect y="20" width="90" height="20" fill="#2D2A4A" />
    </svg>
  );
}

/** Simplified Union Jack. */
function UkFlag() {
  return (
    <svg viewBox="0 0 90 60" role="img" aria-label="United Kingdom flag">
      <rect width="90" height="60" fill="#012169" />
      <path d="M0,0 L90,60 M90,0 L0,60" stroke="#fff" strokeWidth="12" />
      <path d="M0,0 L90,60 M90,0 L0,60" stroke="#C8102E" strokeWidth="5" />
      <path d="M45,0 V60 M0,30 H90" stroke="#fff" strokeWidth="20" />
      <path d="M45,0 V60 M0,30 H90" stroke="#C8102E" strokeWidth="11" />
    </svg>
  );
}

/**
 * First phase of the kiosk session: pick the conversation language.
 * Flag + native name + greeting + explicit "tap to select" affordance on
 * each card. Deliberately bilingual — no language is chosen yet.
 */
export function LanguageSelect({ onSelect, busy, onExit, error = false }: LanguageSelectProps) {
  const cards = [
    {
      lang: 'th' as AppLanguage,
      flag: <ThaiFlag />,
      word: 'ภาษาไทย',
      hello: 'สวัสดีค่ะ ยินดีให้บริการ',
      cta: 'แตะเพื่อเลือก',
      delay: 0.08,
    },
    {
      lang: 'en' as AppLanguage,
      flag: <UkFlag />,
      word: 'English',
      hello: 'Hello, happy to help',
      cta: 'Tap to select',
      delay: 0.16,
    },
  ];

  return (
    <div className="k-langselect">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: 'easeOut' }}
        style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14 }}
      >
        <span className="k-status-chip">
          <Translate size={18} weight="duotone" aria-hidden="true" />
          ภาษา · Language
        </span>
        <h2 className="k-langselect-title">
          กรุณาเลือกภาษา
          <small>Please select your language</small>
        </h2>
      </motion.div>

      {error && (
        <p className="k-error">
          เราไม่สามารถเริ่มเซสชันของคุณได้ กรุณาลองอีกครั้ง · We couldn’t start your session — please try again
        </p>
      )}

      <div className="k-lang-cards">
        {cards.map((card) => (
          <motion.button
            key={card.lang}
            type="button"
            className="k-lang-card"
            onClick={() => onSelect(card.lang)}
            disabled={busy}
            initial={{ opacity: 0, y: 22 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: card.delay, ease: 'easeOut' }}
            whileTap={{ scale: 0.97 }}
          >
            <span className="k-lang-flag" aria-hidden="true">
              {card.flag}
            </span>
            <span className="k-lang-word">{card.word}</span>
            <span className="k-lang-hello">{card.hello}</span>
            <span className="k-lang-cta">
              <HandTap size={20} weight="duotone" aria-hidden="true" />
              {card.cta}
            </span>
          </motion.button>
        ))}
      </div>

      {busy ? (
        <div className="k-spinner" role="status" aria-label="loading" />
      ) : (
        <motion.button
          type="button"
          className="k-btn secondary"
          onClick={onExit}
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.24, ease: 'easeOut' }}
          whileTap={{ scale: 0.97 }}
        >
          <X size={22} weight="bold" aria-hidden="true" />
          ออก · Exit
        </motion.button>
      )}
    </div>
  );
}
