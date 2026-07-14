import { motion } from 'framer-motion';
import { Languages, X } from 'lucide-react';
import type { AppLanguage } from '../../i18n/resources';

interface LanguageSelectProps {
  onSelect: (lang: AppLanguage) => void;
  /** Disables the cards while the session is being created. */
  busy: boolean;
  /** Back to the home screen — rendered below the cards (bilingual label). */
  onExit: () => void;
}

/**
 * First phase of the kiosk session: pick the conversation language.
 * Deliberately bilingual and label-heavy — the patient hasn't chosen a
 * language yet, so both are always shown side by side.
 */
export function LanguageSelect({ onSelect, busy, onExit }: LanguageSelectProps) {
  return (
    <div className="k-langselect">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: 'easeOut' }}
        style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14 }}
      >
        <span className="k-status-chip">
          <Languages size={18} aria-hidden="true" />
          ภาษา · Language
        </span>
        <h2 className="k-langselect-title">
          กรุณาเลือกภาษา
          <small>Please select your language</small>
        </h2>
      </motion.div>

      <div className="k-lang-cards">
        <motion.button
          type="button"
          className="k-lang-card"
          onClick={() => onSelect('th')}
          disabled={busy}
          initial={{ opacity: 0, y: 22 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.08, ease: 'easeOut' }}
          whileTap={{ scale: 0.97 }}
        >
          <span className="k-lang-word">ภาษาไทย</span>
          <span className="k-lang-hello">สวัสดีค่ะ</span>
        </motion.button>

        <motion.button
          type="button"
          className="k-lang-card"
          onClick={() => onSelect('en')}
          disabled={busy}
          initial={{ opacity: 0, y: 22 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.16, ease: 'easeOut' }}
          whileTap={{ scale: 0.97 }}
        >
          <span className="k-lang-word">English</span>
          <span className="k-lang-hello">Hello</span>
        </motion.button>
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
          <X size={22} aria-hidden="true" />
          ออก · Exit
        </motion.button>
      )}
    </div>
  );
}
