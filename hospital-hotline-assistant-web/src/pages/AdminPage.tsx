import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Book,
  BookOpen,
  ChartBar,
  Buildings,
  ChatsCircle,
  Stethoscope,
  UsersThree,
} from '@phosphor-icons/react';
import { api } from '../api';
import { getAdminEmail, getAdminName, getAdminRole, getAdminToken } from '../api/client';
import { Layout } from '../components/Layout';
import { StaffNav, type StaffNavItem } from '../components/staff/StaffNav';
import { SessionsPanel } from '../components/admin/SessionsPanel';
import { AdminDashboard } from '../components/admin/AdminDashboard';
import { DeviceSettingsPanel } from '../components/admin/DeviceSettingsPanel';
import { TriageManualUpload } from '../components/TriageManualUpload';
import { CriteriaBook } from '../components/CriteriaBook';
import { HospitalDbPanel } from '../components/HospitalDbPanel';
import { UserManagementPanel } from '../components/UserManagementPanel';
import { useLanguage } from '../hooks/useSession';

type AdminTab =
  | 'dashboard'
  | 'sessions'
  | 'triage-manual'
  | 'criteria-book'
  | 'bp-device'
  | 'hospital-db'
  | 'users';

export function AdminPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { language, setLanguage } = useLanguage();
  const [activeTab, setActiveTab] = useState<AdminTab>('dashboard');

  const staffEmail = getAdminEmail() ?? t('loginAdminTab');
  const staffName = getAdminName();

  useEffect(() => {
    if (!getAdminToken()) navigate('/login/admin', { replace: true });
  }, [navigate]);

  const handleLogout = () => {
    api.adminLogout();
    navigate('/login/admin', { replace: true });
  };

  const navItems: Array<StaffNavItem<AdminTab>> = [
    { id: 'dashboard', label: t('dashTab'), icon: ChartBar },
    { id: 'sessions', label: t('adminTitle'), icon: ChatsCircle },
    { id: 'triage-manual', label: t('triageManualTab'), icon: Book },
    { id: 'criteria-book', label: t('criteriaBookTab'), icon: BookOpen },
    { id: 'bp-device', label: t('bpdevTab'), icon: Stethoscope },
    { id: 'hospital-db', label: t('hospitalDbTab'), icon: Buildings },
    ...(getAdminRole() === 'super_admin'
      ? [{ id: 'users' as const, label: t('usersTab'), icon: UsersThree }]
      : []),
  ];

  // The header used to say "100 latest sessions" on every tab, including the
  // dashboard — it described the sessions list wherever you were.
  const SECTION_TEXT: Record<AdminTab, { title: string; subtitle: string }> = {
    dashboard: { title: t('dashTab'), subtitle: t('dashSubtitle') },
    sessions: { title: t('adminTitle'), subtitle: t('adminSubtitle') },
    'triage-manual': { title: t('triageManualTab'), subtitle: t('triageManualSubtitle') },
    'criteria-book': { title: t('criteriaBookTitle'), subtitle: t('criteriaBookSubtitle') },
    'bp-device': { title: t('bpdevTab'), subtitle: t('devSubtitle') },
    'hospital-db': { title: t('hospitalDbTab'), subtitle: t('hospitalDbSubtitle') },
    users: { title: t('usersTab'), subtitle: t('usersSubtitle') },
  };

  return (
    <Layout
      language={language}
      onLanguageChange={setLanguage}
      staffEmail={staffEmail}
      sidebar={
        <StaffNav
          items={navItems}
          active={activeTab}
          onSelect={setActiveTab}
          title={t('adminPortalTitle')}
          accountName={staffName}
          accountEmail={staffEmail}
          onLogout={handleLogout}
        />
      }
    >
      {/* The two tabs whose content is a list that grows with the data own the
          viewport instead of running past it; every other tab is a form or a
          panel and scrolls normally. */}
      <section
        className={`staff-page ${
          activeTab === 'sessions' || activeTab === 'criteria-book' ? 'staff-page-fill' : ''
        }`}
      >
        <header className="staff-page-head">
          <div>
            <h1>{SECTION_TEXT[activeTab].title}</h1>
            <p className="muted">{SECTION_TEXT[activeTab].subtitle}</p>
          </div>
        </header>

        {activeTab === 'dashboard' && <AdminDashboard />}
        {activeTab === 'sessions' && <SessionsPanel />}
        {activeTab === 'triage-manual' && <TriageManualUpload />}
        {activeTab === 'criteria-book' && <CriteriaBook />}
        {activeTab === 'bp-device' && <DeviceSettingsPanel />}
        {activeTab === 'hospital-db' && <HospitalDbPanel />}
        {activeTab === 'users' && <UserManagementPanel />}
      </section>
    </Layout>
  );
}
