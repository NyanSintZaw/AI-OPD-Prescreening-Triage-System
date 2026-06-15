import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import { getAdminEmail, getAdminToken } from '../api/client';
import { Layout } from '../components/Layout';
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
  const [reviewFilter, setReviewFilter] = useState<'all' | 'pending' | 'approved' | 'corrected'>(
    'pending',
  );
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
              {t('adminRefresh')}
            </button>
            <Link to="/patient" className="back-link">
              {t('loginPatientAccess')}
            </Link>
          </div>
        </header>

        <div className="chip-group" role="group" aria-label={t('status')}>
          <span className="chip-group-label">{t('status')}</span>
          {(['pending', 'approved', 'corrected', 'all'] as const).map((status) => (
            <button
              key={status}
              type="button"
              className={`filter-chip tone-neutral ${reviewFilter === status ? 'active' : ''}`}
              onClick={() => setReviewFilter(status)}
            >
              {status === 'all' ? t('filterAll') : t(`review_${status}`)}
            </button>
          ))}
        </div>

        {authError ? <p className="error-text">{authError}</p> : null}

        {reviewDataLoading ? (
          <p className="muted">{t('loading')}</p>
        ) : reviews.length === 0 ? (
          <p className="muted">{t('adminNoReviews')}</p>
        ) : (
          <div className="admin-review-list">
            {reviews.map((review) => (
              <article key={review.id} className="admin-review-item">
                <div className="admin-review-item-head">
                  <strong>{truncateId(review.session_id)}</strong>
                  <span className={`status-pill status-${review.status}`}>
                    {t(`review_${review.status}`)}
                  </span>
                </div>
                <p className="muted">
                  {t('department')}:{' '}
                  {language === 'th'
                    ? review.proposed_department_name_th ?? review.proposed_department_name_en ?? '—'
                    : review.proposed_department_name_en ?? '—'}
                </p>
                <div className="admin-review-actions">
                  <button
                    type="button"
                    className="secondary-btn"
                    disabled={reviewActionLoading === review.assessment_id || review.status !== 'pending'}
                    onClick={() => void handleApprove(review)}
                  >
                    {t('adminApprove')}
                  </button>
                  <select
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
                    className="primary-btn"
                    disabled={
                      reviewActionLoading === review.assessment_id ||
                      review.status !== 'pending' ||
                      !(correctDepartmentByAssessment[review.assessment_id] ?? '')
                    }
                    onClick={() => void handleCorrect(review)}
                  >
                    {t('adminCorrectRoute')}
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}

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
