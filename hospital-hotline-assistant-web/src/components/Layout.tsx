import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { LanguageSwitcher } from './LanguageSwitcher';
import type { AppLanguage } from '../i18n/resources';

const LOGO_URL =
  'https://website01.mch.mfu.ac.th/fileadmin/MFUTemplateStandard/Assets/images/logo/Header_MCH_MFU_Thai.png';

interface LayoutProps {
  language: AppLanguage;
  onLanguageChange: (lang: AppLanguage) => void;
  children: React.ReactNode;
  showAdminLink?: boolean;
  navTitle?: string;
  staffEmail?: string | null;
  onStaffLogout?: () => void;
}

export function Layout({
  language,
  onLanguageChange,
  children,
  showAdminLink = true,
  navTitle,
  staffEmail,
  onStaffLogout,
}: LayoutProps) {
  const { t } = useTranslation();

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="header-top">
          <div className="header-inner">
            <Link to={staffEmail ? '/login' : '/patient'} className="brand">
              <img
                src={LOGO_URL}
                alt={t('hospitalName')}
                className="brand-logo"
              />
            </Link>
            <div className="header-top-actions">
              <LanguageSwitcher language={language} onChange={onLanguageChange} variant="header" />
            </div>
          </div>
        </div>
        <div className="header-nav">
          <div className="header-nav-inner">
            <span className="nav-label">{navTitle ?? t('appName')}</span>
            <div className="header-actions">
              {staffEmail ? (
                <div className="staff-session">
                  <span className="staff-session-email">{staffEmail}</span>
                  {onStaffLogout ? (
                    <button type="button" className="text-link" onClick={onStaffLogout}>
                      {t('adminLogout')}
                    </button>
                  ) : null}
                </div>
              ) : null}
              {showAdminLink && !staffEmail && (
                <Link to="/login" className="text-link">
                  {t('staffLoginLink')}
                </Link>
              )}
            </div>
          </div>
        </div>
      </header>
      <main className="app-main">{children}</main>
      <footer className="app-footer">
        <div className="app-footer-inner">
          <p className="footer-hospital">{t('hospitalName')}</p>
          <p className="footer-disclaimer">{t('disclaimer')}</p>
        </div>
      </footer>
    </div>
  );
}
