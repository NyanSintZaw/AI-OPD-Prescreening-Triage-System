import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { api, type MessageOut } from '../api';
import { getAdminEmail, getAdminToken } from '../api/client';
import { Layout } from '../components/Layout';
import { MessageBubble } from '../components/MessageBubble';
import { DoctorScheduleManager } from '../components/DoctorScheduleManager';
import { useLanguage } from '../hooks/useSession';
import type { AssessmentReviewOut, DepartmentOut, RoutingFeedbackOut } from '../api/types';

type NurseTab = 'reviews' | 'schedules';

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
  const [activeTab, setActiveTab] = useState<NurseTab>('reviews');
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
  const [scoreByAssessment, setScoreByAssessment] = useState<Record<string, string>>({});
  const [contactRequestedOnly, setContactRequestedOnly] = useState(false);
  const [reviewDataLoading, setReviewDataLoading] = useState(true);

  const [selectedReview, setSelectedReview] = useState<AssessmentReviewOut | null>(null);
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

  useEffect(() => {
    if (!selectedReview) return undefined;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [selectedReview]);

  const handleLogout = () => {
    api.adminLogout();
    navigate('/login/nurse', { replace: true });
  };

  const handleApprove = async (review: AssessmentReviewOut) => {
    setReviewActionLoading(review.assessment_id);
    const score = scoreByAssessment[review.assessment_id];
    try {
      await api.approveAssessmentReview(review.assessment_id, {
        ai_assessment_score: score ? Number(score) : null,
      });
      await loadReviewData(reviewFilter);
      setSelectedReview(null);
      setSessionMessages([]);
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
    const score = scoreByAssessment[review.assessment_id];
    try {
      await api.correctAssessmentReview(review.assessment_id, {
        confirmed_department_id: selectedDepartment,
        reason: correctReasonByAssessment[review.assessment_id] || null,
        ai_assessment_score: score ? Number(score) : null,
      });
      await loadReviewData(reviewFilter);
      setSelectedReview(null);
      setSessionMessages([]);
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : t('error'));
    } finally {
      setReviewActionLoading(null);
    }
  };

  const handleOpenReview = async (review: AssessmentReviewOut) => {
    setSelectedReview(review);
    setSessionMessages([]);
    setSessionMessagesLoading(true);
    try {
      const messageData = await api.listMessages(review.session_id);
      setSessionMessages(messageData);
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : t('error'));
    } finally {
      setSessionMessagesLoading(false);
    }
  };

  const handleCloseReview = () => {
    setSelectedReview(null);
    setSessionMessages([]);
  };

  const reviewDeptLabel = (review: AssessmentReviewOut) =>
    language === 'th'
      ? review.proposed_department_name_th ?? review.proposed_department_name_en ?? '—'
      : review.proposed_department_name_en ?? '—';

  const confirmedDeptLabel = (review: AssessmentReviewOut) =>
    language === 'th'
      ? review.confirmed_department_name_th ?? review.confirmed_department_name_en ?? null
      : review.confirmed_department_name_en ?? null;

  const contactLabel = (review: AssessmentReviewOut) => {
    if (review.patient_contact_requested === true) return t('patientContactYes');
    if (review.patient_contact_requested === false) return t('patientContactNo');
    return t('patientContactUnknown');
  };

  const filteredReviews = useMemo(
    () =>
      contactRequestedOnly
        ? reviews.filter((review) => review.patient_contact_requested === true)
        : reviews,
    [contactRequestedOnly, reviews],
  );

  const contactRequestedCount = useMemo(
    () => reviews.filter((review) => review.patient_contact_requested === true).length,
    [reviews],
  );

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
            <h1>{t('nursePortalTitle')}</h1>
            <p className="muted">{t('nursePortalSubtitle')}</p>
          </div>
          <div className="admin-header-actions">
            {activeTab === 'reviews' && (
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
            )}
            <Link to="/patient" className="back-link">
              {t('loginPatientAccess')}
            </Link>
          </div>
        </header>

        {/* ── Tab bar ── */}
        <div className="nurse-tab-bar">
          <button
            type="button"
            className={`nurse-tab-btn ${activeTab === 'reviews' ? 'active' : ''}`}
            onClick={() => setActiveTab('reviews')}
          >
            {t('scheduleTabReviews')}
          </button>
          <button
            type="button"
            className={`nurse-tab-btn ${activeTab === 'schedules' ? 'active' : ''}`}
            onClick={() => setActiveTab('schedules')}
          >
            {t('scheduleTabDoctors')}
          </button>
        </div>

        {authError ? <p className="error-text">{authError}</p> : null}

        {activeTab === 'schedules' && (
          <DoctorScheduleManager departments={departments} />
        )}

        {activeTab === 'reviews' && <div className="admin-toolbar nurse-toolbar">
          <div className="chip-group" role="group" aria-label={t('nurseContactFilterLabel')}>
            <span className="chip-group-label">{t('nurseContactFilterLabel')}</span>
            <button
              type="button"
              className={`filter-chip tone-neutral ${!contactRequestedOnly ? 'active' : ''}`}
              onClick={() => setContactRequestedOnly(false)}
            >
              {t('filterAll')}
            </button>
            <button
              type="button"
              className={`filter-chip tone-urgent ${contactRequestedOnly ? 'active' : ''}`}
              onClick={() => setContactRequestedOnly(true)}
            >
              {t('nurseContactRequestedOnly')} ({contactRequestedCount})
            </button>
          </div>
        </div>}

        {/* ── Review cards ── */}
        {activeTab === 'reviews' && (reviewDataLoading ? (
          <p className="muted">{t('loading')}</p>
        ) : filteredReviews.length === 0 ? (
          <p className="muted">
            {contactRequestedOnly ? t('nurseNoContactRequestedReviews') : t('adminNoReviews')}
          </p>
        ) : (
          <div className="nurse-review-list">
            {filteredReviews.map((review) => {
              const confirmed = confirmedDeptLabel(review);

              return (
                <article
                  key={review.id}
                  className={`nurse-review-card review-${review.status}`}
                >
                  <div className="nurse-card-header">
                    <div className="nurse-card-header-left">
                      <span className={`status-pill status-${review.status}`}>
                        {t(`review_${review.status}`)}
                      </span>
                      <code className="nurse-session-code">{review.session_id}</code>
                    </div>
                    <button
                      type="button"
                      className="nurse-conv-btn"
                      onClick={() => void handleOpenReview(review)}
                    >
                      {t('nurseReviewCase')}
                    </button>
                  </div>

                  <div className="nurse-card-summary-grid">
                    <div className="nurse-card-meta-item">
                      <span className="nurse-card-dept-label">{t('department')}</span>
                      <span className="nurse-card-dept-value">
                        {reviewDeptLabel(review)}
                        {review.status === 'corrected' && confirmed ? ` -> ${confirmed}` : ''}
                      </span>
                    </div>
                    <div className="nurse-card-meta-item">
                      <span className="nurse-card-dept-label">{t('patientContactPreference')}</span>
                      <span className="nurse-card-dept-value">{contactLabel(review)}</span>
                    </div>
                    <div className="nurse-card-meta-item">
                      <span className="nurse-card-dept-label">{t('patientContactPhone')}</span>
                      <span className="nurse-card-dept-value">
                        {review.patient_contact_phone || '—'}
                      </span>
                    </div>
                    {review.patient_contact_preferred_time ? (
                      <div className="nurse-card-meta-item">
                        <span className="nurse-card-dept-label">{t('patientContactPreferredTime')}</span>
                        <span className="nurse-card-dept-value">
                          {review.patient_contact_preferred_time}
                        </span>
                      </div>
                    ) : null}
                    {review.patient_contact_relation ? (
                      <div className="nurse-card-meta-item">
                        <span className="nurse-card-dept-label">{t('patientContactRelation')}</span>
                        <span className="nurse-card-dept-value">
                          {review.patient_contact_relation}
                        </span>
                      </div>
                    ) : null}
                  </div>

                  {review.reviewed_at && (
                    <div className="nurse-card-reviewed-at">
                      {review.reviewer_name && (
                        <span className="nurse-card-reviewer">{review.reviewer_name}</span>
                      )}
                      <span className="nurse-card-time">{formatDateAbsolute(review.reviewed_at)}</span>
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        ))}

        {activeTab === 'reviews' && selectedReview && (
          <div className="nurse-review-modal" role="dialog" aria-modal="true" aria-labelledby="nurse-review-modal-title">
            <button
              type="button"
              className="nurse-review-modal-backdrop"
              aria-label={t('close')}
              onClick={handleCloseReview}
            />
            <div className="nurse-review-modal-card">
              <div className="nurse-review-modal-header">
                <div>
                  <p className="nurse-review-modal-kicker">{t('nurseCaseReview')}</p>
                  <h2 id="nurse-review-modal-title">
                    {selectedReview.session_id}
                  </h2>
                </div>
                <button
                  type="button"
                  className="icon-btn nurse-review-modal-close"
                  onClick={handleCloseReview}
                  aria-label={t('close')}
                >
                  {'\u00D7'}
                </button>
              </div>

              <div className="nurse-review-modal-body">
                <aside className="nurse-review-decision-panel">
                  <div className="nurse-review-facts">
                    <div>
                      <span className="nurse-card-dept-label">{t('department')}</span>
                      <strong>{reviewDeptLabel(selectedReview)}</strong>
                    </div>
                    <div>
                      <span className="nurse-card-dept-label">{t('patientContactPreference')}</span>
                      <strong>{contactLabel(selectedReview)}</strong>
                    </div>
                    <div>
                      <span className="nurse-card-dept-label">{t('patientContactPhone')}</span>
                      <strong>{selectedReview.patient_contact_phone || '—'}</strong>
                    </div>
                    {selectedReview.patient_contact_preferred_time ? (
                      <div>
                        <span className="nurse-card-dept-label">{t('patientContactPreferredTime')}</span>
                        <strong>{selectedReview.patient_contact_preferred_time}</strong>
                      </div>
                    ) : null}
                    {selectedReview.patient_contact_relation ? (
                      <div>
                        <span className="nurse-card-dept-label">{t('patientContactRelation')}</span>
                        <strong>{selectedReview.patient_contact_relation}</strong>
                      </div>
                    ) : null}
                  </div>

                  {selectedReview.status === 'pending' ? (
                    <>
                      <label className="nurse-score-field nurse-modal-field">
                        <span>{t('aiAssessmentScore')}</span>
                        <select
                          className="nurse-score-select"
                          value={scoreByAssessment[selectedReview.assessment_id] ?? ''}
                          onChange={(e) =>
                            setScoreByAssessment((prev) => ({
                              ...prev,
                              [selectedReview.assessment_id]: e.target.value,
                            }))
                          }
                        >
                          <option value="">{t('aiAssessmentScorePlaceholder')}</option>
                          {Array.from({ length: 10 }, (_, index) => index + 1).map((score) => (
                            <option key={score} value={score}>
                              {score}/10
                            </option>
                          ))}
                        </select>
                      </label>

                      <div className="nurse-modal-correction">
                        <p className="nurse-review-section-title">{t('nurseDepartmentDecision')}</p>
                        <select
                          className="nurse-dept-select"
                          value={correctDepartmentByAssessment[selectedReview.assessment_id] ?? ''}
                          onChange={(e) =>
                            setCorrectDepartmentByAssessment((prev) => ({
                              ...prev,
                              [selectedReview.assessment_id]: e.target.value,
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
                          value={correctReasonByAssessment[selectedReview.assessment_id] ?? ''}
                          onChange={(e) =>
                            setCorrectReasonByAssessment((prev) => ({
                              ...prev,
                              [selectedReview.assessment_id]: e.target.value,
                            }))
                          }
                        />
                      </div>

                      <div className="nurse-review-modal-actions">
                        <button
                          type="button"
                          className="nurse-approve-btn"
                          disabled={reviewActionLoading === selectedReview.assessment_id}
                          onClick={() => void handleApprove(selectedReview)}
                        >
                          <span aria-hidden="true">{'\u2713'}</span>
                          {t('nurseApproveAssessment')}
                        </button>
                        <button
                          type="button"
                          className="nurse-correct-btn"
                          disabled={
                            reviewActionLoading === selectedReview.assessment_id ||
                            !(correctDepartmentByAssessment[selectedReview.assessment_id] ?? '')
                          }
                          onClick={() => void handleCorrect(selectedReview)}
                        >
                          {t('adminCorrectRoute')}
                        </button>
                      </div>
                    </>
                  ) : selectedReview.ai_assessment_score ? (
                    <div className="nurse-review-facts">
                      <div>
                        <span className="nurse-card-dept-label">{t('aiAssessmentScore')}</span>
                        <strong>
                          {selectedReview.ai_assessment_score}/{selectedReview.ai_assessment_scale}
                        </strong>
                      </div>
                    </div>
                  ) : null}
                </aside>

                <section className="nurse-review-transcript-panel">
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
                    <div className="nurse-conv-messages nurse-modal-messages">
                      {sessionMessages.map((message) => (
                        <MessageBubble key={message.id} message={message} />
                      ))}
                    </div>
                  )}
                </section>
              </div>
            </div>
          </div>
        )}

        {/* ── Routing feedback history ── */}
        {activeTab === 'reviews' && <section className="admin-feedback-section">
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
        </section>}
      </section>
    </Layout>
  );
}
