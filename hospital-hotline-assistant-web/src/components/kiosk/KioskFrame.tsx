import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { X } from '@phosphor-icons/react';
import type { AppLanguage } from '../../i18n/resources';
import { Wordmark } from '../../design-system/components/Mark';

interface KioskFrameProps {
  language: AppLanguage;
  onLanguageChange: (lang: AppLanguage) => void;
  /** Rendered centered in the top bar (the session step indicator). */
  center?: ReactNode;
  /** When set, shows a labeled Exit pill next to the brand. */
  onExit?: () => void;
  /** Hide the top-bar language toggle (e.g. on the language-select phase). */
  hideLanguage?: boolean;
  children: ReactNode;
}

/** Hold the lockup this long to send the booth back to the attract loop. */
const STAFF_HOLD_MS = 1500;

/** Live HH:mm clock — a small production touch every real kiosk has. */
function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const tick = () => setNow(new Date());
    const timer = setInterval(tick, 30_000);
    return () => clearInterval(timer);
  }, []);
  const hh = String(now.getHours()).padStart(2, '0');
  const mm = String(now.getMinutes()).padStart(2, '0');
  return (
    <span className="k-clock" aria-hidden="true">
      {hh}:{mm}
    </span>
  );
}

/**
 * Booth chrome: soft neutral canvas + a clean white top bar with the
 * hospital brand, an optional centered step indicator, a live clock and the
 * TH/EN language toggle. All kiosk screens render inside this frame.
 */
export function KioskFrame({
  language,
  onLanguageChange,
  center,
  onExit,
  hideLanguage = false,
  children,
}: KioskFrameProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  // Staff shortcut back to the attract loop: hold the lockup for 1.5s. A
  // patient never presses and holds a logo, so this cannot fire by accident,
  // and it needs no visible control competing with the primary action.
  const holdTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const startHold = () => {
    clearTimeout(holdTimer.current);
    holdTimer.current = setTimeout(() => navigate('/kiosk/attract'), STAFF_HOLD_MS);
  };
  const cancelHold = () => clearTimeout(holdTimer.current);
  useEffect(() => () => clearTimeout(holdTimer.current), []);

  return (
    <div className="kiosk-root">
      <div className="kiosk-aurora" aria-hidden="true" />

      <header className="kiosk-topbar">
        <div className="k-topbar-left">
          {/* MALI lockup + the hospital's bilingual name. The name is a fixed
              operational mark, so both lines always show regardless of the
              selected UI language. */}
          <div
            className="k-brand"
            onPointerDown={startHold}
            onPointerUp={cancelHold}
            onPointerLeave={cancelHold}
            onPointerCancel={cancelHold}
          >
            <Wordmark height={26} />
            <span className="k-brand-rule" aria-hidden="true" />
            <span className="k-brand-text">
              <span className="k-brand-name">โรงพยาบาลศูนย์การแพทย์มหาวิทยาลัยแม่ฟ้าหลวง</span>
              <span className="k-brand-sub">MAE FAH LUANG UNIVERSITY MEDICAL CENTER HOSPITAL</span>
            </span>
          </div>
        </div>

        <div className="k-topbar-center">{center}</div>

        <div className="k-topbar-right">
          <Clock />
          {!hideLanguage && (
            <div className="k-lang" role="group" aria-label={t('selectLanguage')}>
              <button
                type="button"
                className={language === 'th' ? 'active' : ''}
                onClick={() => onLanguageChange('th')}
                aria-pressed={language === 'th'}
              >
                ไทย
              </button>
              <button
                type="button"
                className={language === 'en' ? 'active' : ''}
                onClick={() => onLanguageChange('en')}
                aria-pressed={language === 'en'}
              >
                EN
              </button>
            </div>
          )}
          {onExit && (
            <button type="button" className="k-exit" onClick={onExit}>
              <X size={20} weight="bold" aria-hidden="true" />
              {t('kioskExit')}
            </button>
          )}
        </div>
      </header>

      <main className="kiosk-shell">{children}</main>
    </div>
  );
}
