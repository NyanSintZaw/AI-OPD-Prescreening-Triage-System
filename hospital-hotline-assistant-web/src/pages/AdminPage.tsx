import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Book,
  BookOpen,
  ChartBar,
  Buildings,
  ChatsCircle,
  ListChecks,
  Stethoscope,
  UsersThree,
} from '@phosphor-icons/react';
import {
  api,
  type ConversationSummaryOut,
  type MessageOut,
} from '../api';
import { getAdminEmail, getAdminName, getAdminRole, getAdminToken } from '../api/client';
import { Layout } from '../components/Layout';
import { MessageBubble } from '../components/MessageBubble';
import { BpDeviceManager } from '../components/BpDeviceManager';
import { TempDeviceManager } from '../components/TempDeviceManager';
import { Spo2DeviceManager } from '../components/Spo2DeviceManager';
import { TriageDashboard } from '../components/TriageDashboard';
import { StaffNav, type StaffNavItem } from '../components/staff/StaffNav';
import { TriageManualUpload } from '../components/TriageManualUpload';
import { CriteriaManager } from '../components/CriteriaManager';
import { CriteriaBook } from '../components/CriteriaBook';
import { HospitalDbPanel } from '../components/HospitalDbPanel';
import { UserManagementPanel } from '../components/UserManagementPanel';
import { useLanguage } from '../hooks/useSession';
import type { SessionStatus, SeverityLevel } from '../api/types';

type AdminTab =
  | 'sessions'
  | 'dashboard'
  | 'triage-manual'
  | 'criteria'
  | 'criteria-book'
  | 'bp-device'
  | 'hospital-db'
  | 'users';

const AUTO_REFRESH_INTERVAL_MS = 30_000;
const SEVERITY_FILTERS: Array<{ id: 'all' | SeverityLevel; tone: string }> = [
  { id: 'all', tone: 'neutral' },
  { id: 'emergency', tone: 'emergency' },
  { id: 'urgent', tone: 'urgent' },
  { id: 'general', tone: 'general' },
  { id: 'unknown', tone: 'unknown' },
];
const STATUS_FILTERS: Array<'all' | SessionStatus> = [
  'all',
  'active',
  'escalated',
  'completed',
  'reset',
];
const LANGUAGE_FILTERS: Array<'all' | 'th' | 'en'> = ['all', 'en', 'th'];

function truncateId(id: string): string {
  return `${id.slice(0, 8)}…`;
}

function formatDateAbsolute(value: string | null): string {
  if (!value) return '—';
  return new Date(value).toLocaleString();
}

function relativeTime(value: string | null, t: (k: string, opts?: Record<string, unknown>) => string): string {
  if (!value) return '—';
  const then = new Date(value).getTime();
  const diffMs = Date.now() - then;
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return t('justNow');
  if (diffMin < 60) return t('minutesAgoShort', { n: diffMin });
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return t('hoursAgoShort', { n: diffH });
  const diffD = Math.floor(diffH / 24);
  return t('daysAgoShort', { n: diffD });
}

function lastRefreshedLabel(date: Date | null): string {
  if (!date) return '';
  return date.toLocaleTimeString();
}

export function AdminPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { language, setLanguage } = useLanguage();
  const [sessions, setSessions] = useState<ConversationSummaryOut[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<MessageOut[]>([]);
  const [emergencyEvents, setEmergencyEvents] = useState<
    Array<{ id: string; alert_message: string; created_at: string }>
  >([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [severityFilter, setSeverityFilter] = useState<'all' | SeverityLevel>('all');
  const [languageFilter, setLanguageFilter] = useState<'all' | 'th' | 'en'>('all');
  const [statusFilter, setStatusFilter] = useState<'all' | SessionStatus>('all');
  const [search, setSearch] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [isBigView, setIsBigView] = useState(false);
  const [activeTab, setActiveTab] = useState<AdminTab>('sessions');

  const staffEmail = getAdminEmail() ?? t('loginAdminTab');
  const staffName = getAdminName();

  const loadSummary = async (options: { initial?: boolean } = {}) => {
    if (options.initial) {
      setIsLoading(true);
    } else {
      setIsRefreshing(true);
    }
    setError(null);
    try {
      const data = await api.getConversationSummary();
      setSessions(data);
      setLastRefreshed(new Date());
    } catch (err) {
      const message = err instanceof Error ? err.message : t('error');
      // Only a stale token warrants a logout — a 403 means the role lacks
      // the permission, which signing out again will not fix.
      if (
        message.includes('401') ||
        message.toLowerCase().includes('token') ||
        message.toLowerCase().includes('unauthorized')
      ) {
        api.adminLogout();
        navigate('/login/admin', { replace: true });
        return;
      }
      setError(message);
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  // Initial load
  useEffect(() => {
    if (!getAdminToken()) {
      navigate('/login/admin', { replace: true });
      return;
    }
    void loadSummary({ initial: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-refresh
  const autoRefreshRef = useRef(autoRefresh);
  autoRefreshRef.current = autoRefresh;
  useEffect(() => {
    if (!autoRefresh) return;
    const id = window.setInterval(() => {
      if (!autoRefreshRef.current) return;
      if (document.visibilityState !== 'visible') return;
      void loadSummary();
    }, AUTO_REFRESH_INTERVAL_MS);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRefresh]);

  const handleSelectSession = async (sessionId: string) => {
    if (selectedSessionId === sessionId) {
      setSelectedSessionId(null);
      setMessages([]);
      setEmergencyEvents([]);
      return;
    }

    setSelectedSessionId(sessionId);
    setMessagesLoading(true);
    try {
      const [messageData, eventData] = await Promise.all([
        api.listMessages(sessionId),
        api.listEmergencyEvents(sessionId),
      ]);
      setMessages(messageData);
      setEmergencyEvents(
        eventData.map((event) => ({
          id: event.id,
          alert_message: event.alert_message,
          created_at: event.created_at,
        })),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : t('error'));
    } finally {
      setMessagesLoading(false);
    }
  };

  const handleCopyId = async (id: string) => {
    try {
      await navigator.clipboard.writeText(id);
      setCopiedId(id);
      window.setTimeout(() => {
        setCopiedId((current) => (current === id ? null : current));
      }, 1500);
    } catch {
      // ignore — non-secure contexts may block clipboard
    }
  };

  const handleLogout = () => {
    api.adminLogout();
    navigate('/login/admin', { replace: true });
  };

  const departmentName = (row: ConversationSummaryOut) =>
    language === 'th'
      ? row.department_name_th ?? row.department_name_en ?? '—'
      : row.department_name_en ?? '—';

  const filteredSessions = useMemo(() => {
    const term = search.trim().toLowerCase();
    const filtered = sessions.filter((row) => {
      const severityOk = severityFilter === 'all' || row.severity === severityFilter;
      const languageOk = languageFilter === 'all' || row.language === languageFilter;
      const statusOk = statusFilter === 'all' || row.status === statusFilter;
      const searchOk = !term || row.session_id.toLowerCase().includes(term);
      return severityOk && languageOk && statusOk && searchOk;
    });

    return filtered.sort((a, b) => {
      if (a.status === 'completed' && b.status !== 'completed') return 1;
      if (a.status !== 'completed' && b.status === 'completed') return -1;
      return 0;
    });
  }, [sessions, severityFilter, languageFilter, statusFilter, search]);

  const selectedSession = useMemo(
    () => sessions.find((row) => row.session_id === selectedSessionId) ?? null,
    [sessions, selectedSessionId],
  );

  const filtersActive =
    severityFilter !== 'all' || languageFilter !== 'all' || statusFilter !== 'all' || search.trim().length > 0;

  const resetFilters = () => {
    setSeverityFilter('all');
    setLanguageFilter('all');
    setStatusFilter('all');
    setSearch('');
  };

  const navItems: Array<StaffNavItem<AdminTab>> = [
    { id: 'sessions', label: t('adminTitle'), icon: ChatsCircle },
    { id: 'dashboard', label: t('dashTab'), icon: ChartBar },
    { id: 'triage-manual', label: t('triageManualTab'), icon: Book },
    { id: 'criteria', label: t('criteriaTab'), icon: ListChecks },
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
    sessions: { title: t('adminTitle'), subtitle: t('adminSubtitle') },
    dashboard: { title: t('dashTab'), subtitle: t('dashSubtitle') },
    'triage-manual': { title: t('triageManualTab'), subtitle: t('triageManualSubtitle') },
    criteria: { title: t('criteriaTab'), subtitle: t('criteriaSubtitle') },
    'criteria-book': { title: t('criteriaBookTitle'), subtitle: t('criteriaBookSubtitle') },
    'bp-device': { title: t('bpdevTab'), subtitle: t('bpdevSubtitle') },
    'hospital-db': { title: t('hospitalDbTab'), subtitle: t('hospitalDbSubtitle') },
    users: { title: t('usersTab'), subtitle: t('usersSubtitle') },
  };
  const sectionTitle = SECTION_TEXT[activeTab].title;
  const sectionSubtitle = SECTION_TEXT[activeTab].subtitle;

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
      <section className="staff-page">
        <header className="staff-page-head">
          <div>
            <h1>{sectionTitle}</h1>
            <p className="muted">{sectionSubtitle}</p>
          </div>
          {activeTab === 'sessions' && (
            <div className="staff-head-actions">
              <label className="staff-toggle">
                <input
                  type="checkbox"
                  checked={autoRefresh}
                  onChange={(e) => setAutoRefresh(e.target.checked)}
                />
                <span>{t('adminAutoRefresh')}</span>
              </label>
              <button
                type="button"
                className="secondary-btn"
                onClick={() => void loadSummary()}
                disabled={isRefreshing || isLoading}
              >
                {t('adminRefresh')}
              </button>
              {lastRefreshed ? (
                <span className="muted staff-head-note">
                  {t('adminLastRefreshed')}: {lastRefreshedLabel(lastRefreshed)}
                </span>
              ) : null}
            </div>
          )}
        </header>

        {activeTab === 'dashboard' && <TriageDashboard scope="admin" />}
        {activeTab === 'triage-manual' && <TriageManualUpload />}
        {activeTab === 'criteria' && <CriteriaManager />}
        {activeTab === 'criteria-book' && <CriteriaBook />}
        {activeTab === 'bp-device' && (
          <>
            <BpDeviceManager />
            <TempDeviceManager />
            <Spo2DeviceManager />
          </>
        )}
        {activeTab === 'hospital-db' && <HospitalDbPanel />}
        {activeTab === 'users' && <UserManagementPanel />}

        {activeTab === 'sessions' && (
          <>
        {error && (
          <div className="admin-error">
            <p className="error-text">{error}</p>
            <button type="button" className="secondary-btn" onClick={() => void loadSummary()}>
              {t('retry')}
            </button>
          </div>
        )}

        {isLoading ? (
          <p className="muted">{t('loading')}</p>
        ) : sessions.length === 0 ? (
          <p className="muted">{t('noSessions')}</p>
        ) : (
          <>
            <div className="admin-toolbar">
              <input
                type="search"
                className="admin-search"
                placeholder={t('adminSearchPlaceholder')}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                aria-label={t('adminSearchPlaceholder')}
              />

              <div className="chip-group" role="group" aria-label={t('severity')}>
                <span className="chip-group-label">{t('severity')}</span>
                {SEVERITY_FILTERS.map(({ id, tone }) => (
                  <button
                    key={id}
                    type="button"
                    className={`filter-chip tone-${tone} ${severityFilter === id ? 'active' : ''}`}
                    onClick={() => setSeverityFilter(id)}
                  >
                    {id === 'all' ? t('filterAll') : t(`severity_${id}`)}
                  </button>
                ))}
              </div>

              <div className="chip-group" role="group" aria-label={t('status')}>
                <span className="chip-group-label">{t('status')}</span>
                {STATUS_FILTERS.map((id) => (
                  <button
                    key={id}
                    type="button"
                    className={`filter-chip tone-neutral ${statusFilter === id ? 'active' : ''}`}
                    onClick={() => setStatusFilter(id)}
                  >
                    {id === 'all' ? t('filterAll') : t(`status_${id}`)}
                  </button>
                ))}
              </div>

              <div className="chip-group" role="group" aria-label={t('language')}>
                <span className="chip-group-label">{t('language')}</span>
                {LANGUAGE_FILTERS.map((id) => (
                  <button
                    key={id}
                    type="button"
                    className={`filter-chip tone-neutral ${languageFilter === id ? 'active' : ''}`}
                    onClick={() => setLanguageFilter(id)}
                  >
                    {id === 'all' ? t('filterAll') : id.toUpperCase()}
                  </button>
                ))}
              </div>

              {filtersActive && (
                <button type="button" className="text-btn admin-filter-reset" onClick={resetFilters}>
                  {t('adminFiltersReset')}
                </button>
              )}
            </div>

            <div className="admin-layout">
              <div className="table-wrap">
                {filteredSessions.length === 0 ? (
                  <p className="muted admin-empty">{t('adminEmptyFiltered')}</p>
                ) : (
                  <table className="admin-table">
                    <thead>
                      <tr>
                        <th>{t('severity')}</th>
                        <th>{t('started')}</th>
                        <th>{t('status')}</th>
                        <th>{t('language')}</th>
                        <th>{t('department')}</th>
                        <th className="admin-col-num">{t('messages')}</th>
                        <th>{t('adminAlertColumn')}</th>
                        <th>{t('sessionId')}</th>
                        <th aria-label="actions" />
                      </tr>
                    </thead>
                    <tbody>
                      {filteredSessions.map((row) => (
                        <tr
                          key={row.session_id}
                          className={`admin-row ${
                            selectedSessionId === row.session_id ? 'selected' : ''
                          } ${row.severity === 'emergency' ? 'row-emergency' : ''}`}
                        >
                          <td>
                            {row.severity ? (
                              <span className={`severity-badge severity-${row.severity}`}>
                                {t(`severity_${row.severity as SeverityLevel}`)}
                              </span>
                            ) : (
                              <span className="severity-badge severity-unknown">
                                {t('severity_unknown')}
                              </span>
                            )}
                          </td>
                          <td>
                            <div className="admin-time">
                              <span>{relativeTime(row.started_at, t)}</span>
                              <span className="admin-time-abs">{formatDateAbsolute(row.started_at)}</span>
                            </div>
                          </td>
                          <td>
                            <span className={`status-pill status-${row.status}`}>
                              {t(`status_${row.status as SessionStatus}`)}
                            </span>
                          </td>
                          <td>
                            <span className="lang-pill">{row.language.toUpperCase()}</span>
                          </td>
                          <td className="admin-col-dept">{departmentName(row)}</td>
                          <td className="admin-col-num">{row.message_count}</td>
                          <td>
                            {row.has_alert ? (
                              <span className="alert-pill alert-yes">
                                <span aria-hidden="true">{'\u25CF'}</span>
                                {t('adminAlertYes')}
                              </span>
                            ) : (
                              <span className="alert-pill alert-no">{t('adminAlertNo')}</span>
                            )}
                          </td>
                          <td className="admin-col-id">
                            <code>{truncateId(row.session_id)}</code>
                          </td>
                          <td className="admin-col-actions">
                            <button
                              type="button"
                              className="secondary-btn admin-row-btn"
                              onClick={() => void handleSelectSession(row.session_id)}
                            >
                              {selectedSessionId === row.session_id
                                ? t('close')
                                : t('viewMessages')}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              {selectedSessionId && (
                <aside className={`admin-detail ${isBigView ? 'admin-detail-big' : ''}`}>
                  <div className="admin-detail-header">
                    <h2>{t('adminSessionDetails')}</h2>
                    <div className="admin-detail-header-actions">
                      <button
                        type="button"
                        className="text-btn admin-detail-expand"
                        onClick={() => setIsBigView(!isBigView)}
                        aria-label={t('adminExpandView', 'Toggle expanded view')}
                        title={t('adminExpandView', 'Toggle expanded view')}
                      >
                        {isBigView ? '\u25E4' : '\u25F2'}
                      </button>
                      <button
                        type="button"
                        className="text-btn admin-detail-close"
                        onClick={() => void handleSelectSession(selectedSessionId)}
                        aria-label={t('close')}
                      >
                        {'\u2715'}
                      </button>
                    </div>
                  </div>

                  <div className="admin-detail-id">
                    <code>{selectedSessionId}</code>
                    <button
                      type="button"
                      className="text-btn admin-copy-btn"
                      onClick={() => void handleCopyId(selectedSessionId)}
                    >
                      {copiedId === selectedSessionId ? t('adminCopied') : t('adminCopyId')}
                    </button>
                  </div>

                  {selectedSession && (
                    <dl className="admin-detail-meta">
                      <div>
                        <dt>{t('severity')}</dt>
                        <dd>
                          <span
                            className={`severity-badge severity-${selectedSession.severity ?? 'unknown'}`}
                          >
                            {t(`severity_${(selectedSession.severity ?? 'unknown') as SeverityLevel}`)}
                          </span>
                        </dd>
                      </div>
                      <div>
                        <dt>{t('status')}</dt>
                        <dd>
                          <span className={`status-pill status-${selectedSession.status}`}>
                            {t(`status_${selectedSession.status as SessionStatus}`)}
                          </span>
                        </dd>
                      </div>
                      <div>
                        <dt>{t('language')}</dt>
                        <dd>{selectedSession.language.toUpperCase()}</dd>
                      </div>
                      <div>
                        <dt>{t('department')}</dt>
                        <dd>{departmentName(selectedSession)}</dd>
                      </div>
                      <div>
                        <dt>{t('started')}</dt>
                        <dd>{formatDateAbsolute(selectedSession.started_at)}</dd>
                      </div>
                      <div>
                        <dt>{t('ended')}</dt>
                        <dd>{formatDateAbsolute(selectedSession.ended_at)}</dd>
                      </div>
                      <div>
                        <dt>{t('messages')}</dt>
                        <dd>{selectedSession.message_count}</dd>
                      </div>
                      <div>
                        <dt>{t('adminAlertColumn')}</dt>
                        <dd>
                          {selectedSession.has_alert ? (
                            <span className="alert-pill alert-yes">{t('adminAlertYes')}</span>
                          ) : (
                            <span className="alert-pill alert-no">{t('adminAlertNo')}</span>
                          )}
                        </dd>
                      </div>
                    </dl>
                  )}

                  {emergencyEvents.length > 0 && (
                    <div className="admin-alert-list">
                      <strong>{t('adminEmergencyHistory')}</strong>
                      {emergencyEvents.map((event) => (
                        <p key={event.id} className="admin-alert-item">
                          <span className="admin-alert-time">
                            {new Date(event.created_at).toLocaleString()}
                          </span>
                          {event.alert_message}
                        </p>
                      ))}
                    </div>
                  )}

                  {messagesLoading ? (
                    <p className="muted">{t('loading')}</p>
                  ) : (
                    <div className="admin-messages">
                      {messages.map((message) => (
                        <MessageBubble key={message.id} message={message} />
                      ))}
                    </div>
                  )}
                </aside>
              )}
            </div>
          </>
        )}
          </>
        )}
      </section>
    </Layout>
  );
}


