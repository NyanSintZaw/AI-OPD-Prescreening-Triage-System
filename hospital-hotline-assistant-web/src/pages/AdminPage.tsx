import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { api, type ConversationSummaryOut, type MessageOut } from '../api';
import { Layout } from '../components/Layout';
import { MessageBubble } from '../components/MessageBubble';
import { useLanguage } from '../hooks/useSession';
import type { SessionStatus, SeverityLevel } from '../api/types';

function truncateId(id: string): string {
  return `${id.slice(0, 8)}…`;
}

function formatDate(value: string | null): string {
  if (!value) return '—';
  return new Date(value).toLocaleString();
}

export function AdminPage() {
  const { t } = useTranslation();
  const { language, setLanguage } = useLanguage();
  const [sessions, setSessions] = useState<ConversationSummaryOut[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<MessageOut[]>([]);
  const [emergencyEvents, setEmergencyEvents] = useState<
    Array<{ id: string; alert_message: string; created_at: string }>
  >([]);
  const [isLoading, setIsLoading] = useState(true);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [severityFilter, setSeverityFilter] = useState<string>('all');
  const [languageFilter, setLanguageFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');

  const loadSummary = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await api.getConversationSummary();
      setSessions(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('error'));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadSummary();
  }, []);

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

  const departmentName = (row: ConversationSummaryOut) =>
    language === 'th'
      ? row.department_name_th ?? row.department_name_en ?? '—'
      : row.department_name_en ?? '—';

  const filteredSessions = sessions.filter((row) => {
    const severityOk = severityFilter === 'all' || row.severity === severityFilter;
    const languageOk = languageFilter === 'all' || row.language === languageFilter;
    const statusOk = statusFilter === 'all' || row.status === statusFilter;
    return severityOk && languageOk && statusOk;
  });

  return (
    <Layout language={language} onLanguageChange={setLanguage} showAdminLink={false}>
      <section className="admin-page">
        <div className="admin-header">
          <div>
            <h1>{t('adminTitle')}</h1>
            <p className="muted">{t('adminSubtitle')}</p>
          </div>
          <Link to="/" className="back-link">
            {t('backHome')}
          </Link>
        </div>

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
          <div className="admin-layout">
            <div className="table-wrap">
              <div className="admin-filters">
                <select
                  value={severityFilter}
                  onChange={(e) => setSeverityFilter(e.target.value)}
                >
                  <option value="all">{t('severity')} - all</option>
                  <option value="emergency">{t('severity_emergency')}</option>
                  <option value="urgent">{t('severity_urgent')}</option>
                  <option value="general">{t('severity_general')}</option>
                  <option value="unknown">{t('severity_unknown')}</option>
                </select>
                <select
                  value={languageFilter}
                  onChange={(e) => setLanguageFilter(e.target.value)}
                >
                  <option value="all">{t('language')} - all</option>
                  <option value="th">TH</option>
                  <option value="en">EN</option>
                </select>
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                >
                  <option value="all">{t('status')} - all</option>
                  <option value="active">{t('status_active')}</option>
                  <option value="completed">{t('status_completed')}</option>
                  <option value="reset">{t('status_reset')}</option>
                  <option value="escalated">{t('status_escalated')}</option>
                </select>
              </div>
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>{t('sessionId')}</th>
                    <th>{t('language')}</th>
                    <th>{t('status')}</th>
                    <th>{t('humanAlertSent')}</th>
                    <th>{t('started')}</th>
                    <th>{t('ended')}</th>
                    <th>{t('severity')}</th>
                    <th>{t('department')}</th>
                    <th>{t('messages')}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {filteredSessions.map((row) => (
                    <tr
                      key={row.session_id}
                      className={selectedSessionId === row.session_id ? 'selected' : ''}
                    >
                      <td>{truncateId(row.session_id)}</td>
                      <td>{row.language.toUpperCase()}</td>
                      <td>{t(`status_${row.status as SessionStatus}`)}</td>
                      <td>{row.has_alert ? 'Yes' : 'No'}</td>
                      <td>{formatDate(row.started_at)}</td>
                      <td>{formatDate(row.ended_at)}</td>
                      <td>
                        {row.severity ? (
                          <span className={`severity-badge severity-${row.severity}`}>
                            {t(`severity_${row.severity as SeverityLevel}`)}
                          </span>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td>{departmentName(row)}</td>
                      <td>{row.message_count}</td>
                      <td>
                        <button
                          type="button"
                          className="text-btn"
                          onClick={() => void handleSelectSession(row.session_id)}
                        >
                          {selectedSessionId === row.session_id ? t('close') : t('viewMessages')}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {selectedSessionId && (
              <aside className="admin-detail">
                <h2>{t('viewMessages')}</h2>
                <p className="muted">{truncateId(selectedSessionId)}</p>
                {emergencyEvents.length > 0 && (
                  <div className="admin-alert-list">
                    <strong>{t('emergencyTitle')}</strong>
                    {emergencyEvents.map((event) => (
                      <p key={event.id} className="admin-alert-item">
                        {new Date(event.created_at).toLocaleString()} - {event.alert_message}
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
        )}
      </section>
    </Layout>
  );
}
