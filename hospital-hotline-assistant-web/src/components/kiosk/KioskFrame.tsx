import { useEffect, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import type { AppLanguage } from '../../i18n/resources';
import mfuMonogram from '../../assets/mfu-monogram.png';

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

  return (
    <div className="kiosk-root">
      <div className="kiosk-aurora" aria-hidden="true" />

      <header className="kiosk-topbar">
        <div className="k-topbar-left">
          {/* Official hospital lockup (matches the legacy system header):
              royal monogram · red rule · bilingual name. The lockup is a
              fixed brand mark, so both lines always show regardless of the
              selected UI language. */}
          <div className="k-brand">
            <img className="k-brand-emblem" src={mfuMonogram} alt="" />
            <span className="k-brand-rule" aria-hidden="true" />
            <span className="k-brand-text">
              <span className="k-brand-name">โรงพยาบาลศูนย์การแพทย์มหาวิทยาลัยแม่ฟ้าหลวง</span>
              <span className="k-brand-sub">MAE FAH LUANG UNIVERSITY MEDICAL CENTER HOSPITAL</span>
            </span>
          </div>
          {onExit && (
            <button type="button" className="k-exit" onClick={onExit}>
              <X size={20} aria-hidden="true" />
              {t('kioskExit')}
            </button>
          )}
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
        </div>
      </header>

      <main className="kiosk-shell">{children}</main>
    </div>
  );
}
