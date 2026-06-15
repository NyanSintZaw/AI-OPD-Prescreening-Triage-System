import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import { getAdminEmail, getAdminRole, getAdminToken, type StaffRole } from '../api/client';
import { LanguageSwitcher } from '../components/LanguageSwitcher';
import { useLanguage } from '../hooks/useSession';

const LOGO_URL =
  'https://website01.mch.mfu.ac.th/fileadmin/MFUTemplateStandard/Assets/images/logo/Header_MCH_MFU_Thai.png';

type PortalKind = 'nurse' | 'admin';

const PORTAL_ROLES: Record<PortalKind, StaffRole[]> = {
  nurse: ['admin'],
  admin: ['super_admin', 'viewer'],
};

const PORTAL_DEFAULTS: Record<PortalKind, { email: string }> = {
  nurse: { email: 'opd.nurse@mfu.local' },
  admin: { email: 'ops.admin@mfu.local' },
};

function portalFromParam(value: string | undefined): PortalKind {
  return value === 'admin' ? 'admin' : 'nurse';
}

function EyeIcon({ open }: { open: boolean }) {
  if (open) {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 4.5C7 4.5 2.7 7.6 1 12c1.7 4.4 6 7.5 11 7.5s9.3-3.1 11-7.5c-1.7-4.4-6-7.5-11-7.5zm0 12.5a5 5 0 1 1 0-10 5 5 0 0 1 0 10zm0-2.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3.3 4.7 4.7 3.3 20.7 19.3l-1.4 1.4-3.2-3.2A11.8 11.8 0 0 1 12 19.5C7 19.5 2.7 16.4 1 12a12.8 12.8 0 0 1 4.1-5.5L3.3 4.7zM12 6.5c2.2 0 4.2.9 5.7 2.3l-1.4 1.4A5 5 0 0 0 7.7 14l-1.7 1.7A11.6 11.6 0 0 1 1 12c1.7-4.4 6-7.5 11-7.5.8 0 1.6.1 2.4.2l-1.6 1.6A5 5 0 0 0 12 6.5z" />
    </svg>
  );
}

export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { portal: portalParam } = useParams<{ portal?: string }>();
  const portal = portalFromParam(portalParam);
  const { language, setLanguage } = useLanguage();
  const [email, setEmail] = useState(PORTAL_DEFAULTS[portal].email);
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const allowedRoles = PORTAL_ROLES[portal];

  const redirectForRole = useMemo(
    () =>
      ({
        admin: '/nurse',
        super_admin: '/admin',
        viewer: '/admin',
      }) satisfies Record<StaffRole, string>,
    [],
  );

  useEffect(() => {
    const token = getAdminToken();
    const role = getAdminRole();
    const savedEmail = getAdminEmail();
    if (token && role && savedEmail && allowedRoles.includes(role)) {
      navigate(redirectForRole[role], { replace: true });
    }
  }, [allowedRoles, navigate, redirectForRole]);

  useEffect(() => {
    setEmail(PORTAL_DEFAULTS[portal].email);
    setPassword('');
    setError(null);
  }, [portal]);

  const switchPortal = (next: PortalKind) => {
    navigate(`/login/${next}`, { replace: true });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await api.adminLogin({ email: email.trim(), password });
      if (!allowedRoles.includes(res.user.role)) {
        api.adminLogout();
        setError(t('loginWrongPortal'));
        return;
      }
      navigate(redirectForRole[res.user.role], { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : t('error'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="portal-shell">
      <header className="portal-header">
        <div className="portal-header-inner">
          <div className="portal-brand">
            <img src={LOGO_URL} alt={t('hospitalName')} className="portal-logo" />
          </div>
          <LanguageSwitcher language={language} onChange={setLanguage} variant="header" />
        </div>
      </header>

      <main className="portal-main">
        <div className="portal-card">
          <div className="portal-tabs" role="tablist" aria-label={t('loginPortalSwitch')}>
            <button
              type="button"
              role="tab"
              aria-selected={portal === 'nurse'}
              className={portal === 'nurse' ? 'portal-tab active' : 'portal-tab'}
              onClick={() => switchPortal('nurse')}
            >
              {t('loginNurseTab')}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={portal === 'admin'}
              className={portal === 'admin' ? 'portal-tab active' : 'portal-tab'}
              onClick={() => switchPortal('admin')}
            >
              {t('loginAdminTab')}
            </button>
          </div>

          <h1>{t('loginSignIn')}</h1>
          <p className="portal-subtitle muted">
            {t(portal === 'nurse' ? 'loginNurseHint' : 'loginAdminHint')}
          </p>

          <form className="portal-form" onSubmit={(e) => void handleSubmit(e)}>
            <label className="portal-field">
              <span>{t('loginUsername')}</span>
              <input
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </label>

            <label className="portal-field">
              <span>{t('loginPassword')}</span>
              <div className="portal-password-wrap">
                <input
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
                <button
                  type="button"
                  className="portal-password-toggle"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? t('loginHidePassword') : t('loginShowPassword')}
                >
                  <EyeIcon open={showPassword} />
                </button>
              </div>
            </label>

            {error ? <p className="error-text portal-error">{error}</p> : null}

            <button type="submit" className="portal-submit" disabled={loading}>
              {loading ? t('loading') : t('loginSignIn')}
            </button>
          </form>

          <div className="portal-divider" />

          <Link to="/patient" className="portal-patient-btn">
            {t('loginPatientAccess')}
          </Link>
          <p className="portal-patient-note muted">{t('loginPatientNote')}</p>
        </div>
      </main>
    </div>
  );
}
