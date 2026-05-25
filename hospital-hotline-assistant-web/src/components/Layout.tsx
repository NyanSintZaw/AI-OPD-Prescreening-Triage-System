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
}

export function Layout({
  language,
  onLanguageChange,
  children,
  showAdminLink = true,
  navTitle,
}: LayoutProps) {
  const { t } = useTranslation();

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="header-top">
          <div className="header-inner">
            <Link to="/" className="brand">
              <img
                src={LOGO_URL}
                alt={t('hospitalName')}
                className="brand-logo"
              />
              <span className="brand-text">
                <span className="brand-title">{t('hospitalNameShort')}</span>
                <span className="brand-subtitle">{t('hospitalNameEn')}</span>
              </span>
            </Link>
          </div>
        </div>
        <div className="header-nav">
          <div className="header-nav-inner">
            <span className="nav-label">{navTitle ?? t('appName')}</span>
            <div className="header-actions">
              <LanguageSwitcher language={language} onChange={onLanguageChange} />
              {showAdminLink && (
                <Link to="/admin" className="text-link">
                  {t('adminLink')}
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
