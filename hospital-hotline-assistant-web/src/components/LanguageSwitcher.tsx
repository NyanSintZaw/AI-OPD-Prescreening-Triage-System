import { useTranslation } from 'react-i18next';
import type { AppLanguage } from '../i18n/resources';

interface LanguageSwitcherProps {
  language: AppLanguage;
  onChange: (lang: AppLanguage) => void;
}

export function LanguageSwitcher({ language, onChange }: LanguageSwitcherProps) {
  const { t } = useTranslation();

  return (
    <div className="language-switcher" role="group" aria-label={t('selectLanguage')}>
      <button
        type="button"
        className={language === 'th' ? 'lang-btn active' : 'lang-btn'}
        onClick={() => onChange('th')}
      >
        {t('thai')}
      </button>
      <button
        type="button"
        className={language === 'en' ? 'lang-btn active' : 'lang-btn'}
        onClick={() => onChange('en')}
      >
        {t('english')}
      </button>
    </div>
  );
}
