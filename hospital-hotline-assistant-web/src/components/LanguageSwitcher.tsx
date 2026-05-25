import { useTranslation } from 'react-i18next';
import type { AppLanguage } from '../i18n/resources';

interface LanguageSwitcherProps {
  language: AppLanguage;
  onChange: (lang: AppLanguage) => void;
  /** 'header' = MFU-style round TH/EN circles in the white top band */
  variant?: 'header' | 'nav';
}

export function LanguageSwitcher({
  language,
  onChange,
  variant = 'nav',
}: LanguageSwitcherProps) {
  const { t } = useTranslation();

  const wrapperClass =
    variant === 'header' ? 'language-switcher language-switcher-header' : 'language-switcher';

  const btnClass = variant === 'header' ? 'lang-circle-btn' : 'lang-btn';

  return (
    <div className={wrapperClass} role="group" aria-label={t('selectLanguage')}>
      <button
        type="button"
        className={language === 'th' ? `${btnClass} active` : btnClass}
        onClick={() => onChange('th')}
        aria-label={t('thai')}
      >
        TH
      </button>
      <button
        type="button"
        className={language === 'en' ? `${btnClass} active` : btnClass}
        onClick={() => onChange('en')}
        aria-label={t('english')}
      >
        EN
      </button>
    </div>
  );
}
