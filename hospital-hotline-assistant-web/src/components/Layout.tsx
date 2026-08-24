import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { LanguageSwitcher } from './LanguageSwitcher';
import { ReviewsFab } from './ReviewsFab';
import type { AppLanguage } from '../i18n/resources';

import { Wordmark } from '../design-system/components/Mark';

interface LayoutProps {
  language: AppLanguage;
  onLanguageChange: (lang: AppLanguage) => void;
  children: React.ReactNode;
  /** Only used to point the brand link at the right home. */
  staffEmail?: string | null;
  /** Staff portals render their section nav here; `app-main` becomes a
   *  two-column grid. Omitted on any page without one. */
  sidebar?: React.ReactNode;
}

export function Layout({
  language,
  onLanguageChange,
  children,
  staffEmail,
  sidebar,
}: LayoutProps) {
  const { t } = useTranslation();

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="header-top">
          <div className="header-inner">
            <Link to={staffEmail ? '/login' : '/patient'} className="brand">
              <Wordmark height={30} />
              <span className="brand-hospital">{t('hospitalName')}</span>
            </Link>
            <div className="header-top-actions">
              <LanguageSwitcher language={language} onChange={onLanguageChange} variant="header" />
            </div>
          </div>
        </div>
      </header>
      <main className={`app-main ${sidebar ? 'app-main-sidebar' : ''}`}>
        {sidebar}
        {sidebar ? <div className="staff-content">{children}</div> : children}
      </main>
      {/* Staff shortcut to the triage review queue; renders itself only for
          signed-in staff who are not already on that screen. */}
      <ReviewsFab />
    </div>
  );
}
