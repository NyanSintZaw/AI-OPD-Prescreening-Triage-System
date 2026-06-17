import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { api, type MessageOut } from '../api';
import { getAdminEmail, getAdminToken } from '../api/client';
import { Layout } from '../components/Layout';
import { MessageBubble } from '../components/MessageBubble';
import { useLanguage } from '../hooks/useSession';
import type { AssessmentReviewOut, DepartmentOut, RoutingFeedbackOut } from '../api/types';

function truncateId(id: string): string {
  return `${id.slice(0, 8)}…`;
}

function formatDateAbsolute(value: string | null): string {
  if (!value) return '—';
  return new Date(value).toLocaleString();
}

export function NursePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { language, setLanguage } = useLanguage();
  const reviewFilter = 'pending';
  const [reviews, setReviews] = useState<AssessmentReviewOut[]>([]);
  const [feedbackRows, setFeedbackRows] = useState<RoutingFeedbackOut[]>([]);
  const [departments, setDepartments] = useState<DepartmentOut[]>([]);
  const [authError, setAuthError] = useState<string | null>(null);
  const [reviewActionLoading, setReviewActionLoading] = useState<string | null>(null);
  const [correctDepartmentByAssessment, setCorrectDepartmentByAssessment] = useState<
    Record<string, string>
  >({});
  const [correctReasonByAssessment, setCorrectReasonByAssessment] = useState<Record<string, string>>(
    {},
  );
  const [reviewDataLoading, setReviewDataLoading] = useState(true);

  // ── Conversation state (per review item) ──
  const [expandedSessionId, setExpandedSessionId] = useState<string | null>(null);
  const [sessionMessages, setSessionMessages] = useState<MessageOut[]>([]);
  const [sessionMessagesLoading, setSessionMessagesLoading] = useState(false);

  const staffEmail = getAdminEmail() ?? t('loginNurseTab');

  const loadReviewData = async (status: 'all' | 'pending' | 'approved' | 'corrected') => {
    if (!getAdminToken()) return;
    setReviewDataLoading(true);
    setAuthError(null);
    try {
      const [reviewData, feedbackData] = await Promise.all([
        api.listAssessmentReviews(status),
        api.listRoutingFeedback(),
      ]);
      setReviews(reviewData);
      setFeedbackRows(feedbackData);
    } catch (err) {
      const message = err instanceof Error ? err.message : t('error');
      if (
        message.includes('401') ||
        message.includes('403') ||
        message.toLowerCase().includes('token') ||
        message.toLowerCase().includes('unauthorized') ||
        message.toLowerCase().includes('permission')
      ) {
        api.adminLogout();
        navigate('/login/nurse', { replace: true });
        return;
      }
      setAuthError(message);
    } finally {
      setReviewDataLoading(false);
    }
  };

  useEffect(() => {
    void api.listDepartments().then(setDepartments).catch(() => undefined);
    void loadReviewData(reviewFilter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void loadReviewData(reviewFilter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reviewFilter]);

  const handleLogout = () => {
    api.adminLogout();
    navigate('/login/nurse', { replace: true });
  };

  const handleApprove = async (review: AssessmentReviewOut) => {
    setReviewActionLoading(review.assessment_id);
    try {
      await api.approveAssessmentReview(review.assessment_id, {});
      await loadReviewData(reviewFilter);
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : t('error'));
    } finally {
      setReviewActionLoading(null);
    }
  };

  const handleCorrect = async (review: AssessmentReviewOut) => {
    const selectedDepartment = correctDepartmentByAssessment[review.assessment_id];
    if (!selectedDepartment) return;
    setReviewActionLoading(review.assessment_id);
    try {
      await api.correctAssessmentReview(review.assessment_id, {
        confirmed_department_id: selectedDepartment,
        reason: correctReasonByAssessment[review.assessment_id] || null,
      });
      await loadReviewData(reviewFilter);
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : t('error'));
    } finally {
      setReviewActionLoading(null);
    }
  };

  const handleToggleConversation = async (sessionId: string) => {
    if (expandedSessionId === sessionId) {
      setExpandedSessionId(null);
      setSessionMessages([]);
      return;
    }

    setExpandedSessionId(sessionId);
    setSessionMessagesLoading(true);
    try {
      const messageData = await api.listMessages(sessionId);
      setSessionMessages(messageData);
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : t('error'));
    } finally {
      setSessionMessagesLoading(false);
    }
  };

  const reviewDeptLabel = (review: AssessmentReviewOut) =>
    language === 'th'
      ? review.proposed_department_name_th ?? review.proposed_department_name_en ?? '—'
      : review.proposed_department_name_en ?? '—';

  const confirmedDeptLabel = (review: AssessmentReviewOut) =>
    language === 'th'
      ? review.confirmed_department_name_th ?? review.confirmed_department_name_en ?? null
      : review.confirmed_department_name_en ?? null;

  return (
    <Layout
      language={language}
      onLanguageChange={setLanguage}
      showAdminLink={false}
      navTitle={t('nursePortalTitle')}
      staffEmail={staffEmail}
      onStaffLogout={handleLogout}
    >
      <section className="admin-page nurse-page">
        <header className="admin-header">
          <div className="admin-heading">
            <h1>{t('adminReviewQueueTitle')}</h1>
            <p className="muted">{t('nursePortalSubtitle')}</p>
          </div>
          <div className="admin-header-actions">
            <button
              type="button"
              className="secondary-btn admin-refresh-btn"
              onClick={() => void loadReviewData(reviewFilter)}
              disabled={reviewDataLoading}
            >
              <span aria-hidden="true" className={`refresh-glyph ${reviewDataLoading ? 'spinning' : ''}`}>
                {'\u21BB'}
              </span>
              {t('adminRefresh')}
            </button>
            <Link to="/patient" className="back-link">
              {t('loginPatientAccess')}
            </Link>
          </div>
        </header>


        {authError ? <p className="error-text">{authError}</p> : null}

        {/* ── Review cards ── */}
        {reviewDataLoading ? (
          <p className="muted">{t('loading')}</p>
        ) : reviews.length === 0 ? (
          <p className="muted">{t('adminNoReviews')}</p>
        ) : (
          <div className="nurse-review-list">
            {reviews.map((review) => {
              const isExpanded = expandedSessionId === review.session_id;
              const confirmed = confirmedDeptLabel(review);

              return (
                <article
                  key={review.id}
                  className={`nurse-review-card ${isExpanded ? 'expanded' : ''} review-${review.status}`}
                >
                  {/* ── Card header ── */}
                  <div className="nurse-card-header">
                    <div className="nurse-card-header-left">
                      <span className={`status-pill status-${review.status}`}>
                        {t(`review_${review.status}`)}
                      </span>
                      <code className="nurse-session-code">{truncateId(review.session_id)}</code>
                    </div>
                    <button
                      type="button"
                      className={`nurse-conv-btn ${isExpanded ? 'active' : ''}`}
                      onClick={() => void handleToggleConversation(review.session_id)}
                      aria-expanded={isExpanded}
                    >
                      <span className="nurse-conv-btn-icon" aria-hidden="true">
                        {isExpanded ? '\u25B2' : '\u25BC'}
                      </span>
                      {isExpanded ? t('nurseHideConversation') : t('nurseViewConversation')}
                    </button>
                  </div>

                  {/* ── Department info ── */}
                  <div className="nurse-card-dept">
                    <span className="nurse-card-dept-label">{t('department')}</span>
                    <span className="nurse-card-dept-value">{reviewDeptLabel(review)}</span>
                    {review.status === 'corrected' && confirmed && (
                      <>
                        <span className="nurse-card-dept-arrow" aria-hidden="true">{'\u2192'}</span>
                        <span className="nurse-card-dept-corrected">{confirmed}</span>
                      </>
                    )}
                  </div>

                  {review.reviewed_at && (
                    <div className="nurse-card-reviewed-at">
                      {review.reviewer_name && (
                        <span className="nurse-card-reviewer">{review.reviewer_name}</span>
                      )}
                      <span className="nurse-card-time">{formatDateAbsolute(review.reviewed_at)}</span>
                    </div>
                  )}

                  {/* ── Actions (pending only) ── */}
                  {review.status === 'pending' && (
                    <div className="nurse-card-actions">
                      <button
                        type="button"
                        className="nurse-approve-btn"
                        disabled={reviewActionLoading === review.assessment_id}
                        onClick={() => void handleApprove(review)}
                      >
                        <span aria-hidden="true">{'\u2713'}</span>
                        {t('adminApprove')}
                      </button>

                      <div className="nurse-correct-group">
                        <select
                          className="nurse-dept-select"
                          value={correctDepartmentByAssessment[review.assessment_id] ?? ''}
                          onChange={(e) =>
                            setCorrectDepartmentByAssessment((prev) => ({
                              ...prev,
                              [review.assessment_id]: e.target.value,
                            }))
                          }
                        >
                          <option value="">{t('adminSelectDepartment')}</option>
                          {departments
                            .filter((dept) => dept.kind === 'opd')
                            .map((dept) => (
                              <option key={dept.id} value={dept.id}>
                                {language === 'th' ? dept.name_th ?? dept.name_en : dept.name_en}
                              </option>
                            ))}
                        </select>
                        <input
                          type="text"
                          className="nurse-reason-input"
                          placeholder={t('adminCorrectionReasonPlaceholder')}
                          value={correctReasonByAssessment[review.assessment_id] ?? ''}
                          onChange={(e) =>
                            setCorrectReasonByAssessment((prev) => ({
                              ...prev,
                              [review.assessment_id]: e.target.value,
                            }))
                          }
                        />
                        <button
                          type="button"
                          className="nurse-correct-btn"
                          disabled={
                            reviewActionLoading === review.assessment_id ||
                            !(correctDepartmentByAssessment[review.assessment_id] ?? '')
                          }
                          onClick={() => void handleCorrect(review)}
                        >
                          {t('adminCorrectRoute')}
                        </button>
                      </div>
                    </div>
                  )}

                  {/* ── Expanded conversation panel ── */}
                  {isExpanded && (
                    <div className="nurse-conv-panel">
                      <div className="nurse-conv-panel-header">
                        <span className="nurse-conv-panel-title">{t('nurseConversationTitle')}</span>
                        <span className="nurse-conv-panel-count">
                          {sessionMessagesLoading ? '…' : `${sessionMessages.length} ${t('messages').toLowerCase()}`}
                        </span>
                      </div>
                      {sessionMessagesLoading ? (
                        <div className="nurse-conv-loading">
                          <span className="nurse-conv-spinner" aria-hidden="true" />
                          <span>{t('loading')}</span>
                        </div>
                      ) : sessionMessages.length === 0 ? (
                        <p className="muted nurse-conv-empty">{t('noMessages')}</p>
                      ) : (
                        <div className="nurse-conv-messages">
                          {sessionMessages.map((message) => (
                            <MessageBubble key={message.id} message={message} />
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}

        {/* ── Routing feedback history ── */}
        <section className="admin-feedback-section">
          <h2>{t('adminFeedbackTitle')}</h2>
          {feedbackRows.length === 0 ? (
            <p className="muted">{t('adminNoFeedback')}</p>
          ) : (
            <div className="table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>{t('started')}</th>
                    <th>{t('sessionId')}</th>
                    <th>{t('department')}</th>
                    <th>{t('adminCorrectionReason')}</th>
                  </tr>
                </thead>
                <tbody>
                  {feedbackRows.map((row) => (
                    <tr key={row.id}>
                      <td>{formatDateAbsolute(row.created_at)}</td>
                      <td>
                        <code>{truncateId(row.session_id)}</code>
                      </td>
                      <td>
                        {language === 'th'
                          ? row.corrected_department_name_th ?? row.corrected_department_name_en ?? '—'
                          : row.corrected_department_name_en ?? '—'}
                      </td>
                      <td>{row.reason ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </section>
    </Layout>
  );
}
