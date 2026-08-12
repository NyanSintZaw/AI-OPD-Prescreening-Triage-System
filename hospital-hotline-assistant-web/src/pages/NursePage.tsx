import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { api, type MessageOut } from '../api';
import { getAdminEmail, getAdminRole, getAdminToken } from '../api/client';
import { Layout } from '../components/Layout';
import { MessageBubble } from '../components/MessageBubble';
import { CriteriaBook } from '../components/CriteriaBook';
import { DoctorScheduleManager } from '../components/DoctorScheduleManager';
import { useLanguage } from '../hooks/useSession';
import { slipCode, slipSearchKey } from '../utils/slipCode';
import type {
  AssessmentReviewOut,
  SbarFields,
  DepartmentOut,
  RejectedVital,
  RoutingFeedbackOut,
} from '../api/types';

type NurseTab = 'reviews' | 'schedules' | 'criteria';
type ReviewModalTab = 'assessment' | 'conversation' | 'history';
type ReviewFilter = 'all' | 'pending' | 'reviewed';


// The seven iMed SBAR fields, in handover order. `assessment_equipment` is the
// one our system deliberately never fills — it is a clinical judgement.
const SBAR_FIELDS = [
  'situation',
  'background',
  'assessment',
  'assessment_problem',
  'assessment_equipment',
  'recommend',
  'documentation',
] as const;

/**
 * What the hospital said. Branch on `his_routing_status`, NOT on the HTTP
 * status: approve/correct return 200 whatever the HIS did, so the outcome
 * only exists in the body.
 */
function ConfirmResult({
  review,
  onDone,
}: {
  review: AssessmentReviewOut;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const status = review.his_routing_status ?? 'unknown';
  const detail = review.his_routing_message_th;

  if (status === 'pushed') {
    return (
      <>
        <h3>{t('nurseAssignQueued')}</h3>
        {review.his_queue_number ? (
          <>
            <p className="nurse-queue-number">{review.his_queue_number}</p>
            <p className="nurse-sbar-hint">{t('nurseAssignGiveNumber')}</p>
          </>
        ) : (
          // 409 without a result body: the patient IS queued, but the hospital
          // did not tell us the number (our change request 7).
          <p className="nurse-sbar-warning">{t('nurseAssignNoNumber')}</p>
        )}
        <div className="tm-confirm-actions">
          <button type="button" className="nurse-approve-btn" onClick={onDone}>
            {t('close')}
          </button>
        </div>
      </>
    );
  }

  const messages: Record<string, string> = {
    denied: t('nurseAssignDenied'),
    unavailable: t('nurseAssignUnavailable'),
    invalid: t('nurseAssignInvalid'),
    unknown: t('nurseAssignUnknown'),
    skipped: t('nurseAssignSkipped'),
  };
  return (
    <>
      <h3>{t('nurseAssignNotQueued')}</h3>
      <p className="nurse-sbar-warning">{messages[status] ?? t('nurseHisPushFailed')}</p>
      {detail ? <p className="error-text">{detail}</p> : null}
      <div className="tm-confirm-actions">
        <button type="button" onClick={onDone}>
          {t('close')}
        </button>
      </div>
    </>
  );
}

function truncateId(id: string): string {
  return `${id.slice(0, 8)}…`;
}

function formatDateAbsolute(value: string | null): string {
  if (!value) return '—';
  return new Date(value).toLocaleString();
}

function formatBmi(weightKg?: number | null, heightCm?: number | null): string {
  if (!weightKg || !heightCm) return '—';
  const meters = heightCm / 100;
  return (weightKg / (meters * meters)).toFixed(1);
}

function formatNumber(value?: number | null, digits = 0): string {
  if (value === null || value === undefined) return '—';
  return digits > 0 ? value.toFixed(digits) : String(value);
}

/**
 * Flagged stand-in for a vital the engine refused as physiologically
 * impossible. A blank "—" would read as "never measured", which is a very
 * different clinical signal from "the patient told us 50 °C" — the nurse needs
 * to see the number that was actually reported, struck through and explained.
 */
function RejectedVitalValue({
  rejected,
  vitals,
  fallback,
}: {
  rejected?: Record<string, RejectedVital> | null;
  /** Canonical vital keys this grid cell covers (BP covers sbp and dbp). */
  vitals: string[];
  fallback: React.ReactNode;
}) {
  const { t } = useTranslation();
  const hit = vitals.map((key) => rejected?.[key]).find(Boolean);
  if (!hit) return <strong>{fallback}</strong>;
  return (
    <strong className="nurse-vital-rejected" title={t('nurseRejectedVitals')}>
      {'⚠ '}
      <s>{hit.value}</s>
      <span className="nurse-vital-rejected-note">
        {' '}
        {t(`nurseRejectedSource_${hit.source ?? 'reported'}`, { defaultValue: '' })}
        {', '}
        {t(`nurseRejectedReason_${hit.reason}`, { defaultValue: hit.reason })}
      </span>
    </strong>
  );
}

export function NursePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { language, setLanguage } = useLanguage();
  // Ops staff can reach this portal too; viewers get the read-only view and
  // must be sent back to their own login, not the nurse one.
  const isReadOnly = getAdminRole() === 'viewer';
  // The tab lives in the URL so the floating shortcut can land on a specific
  // one — /nurse and /nurse?tab=schedules share a route element, so nothing
  // remounts on a same-route jump and local state would stay stale.
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get('tab');
  const activeTab: NurseTab =
    tabParam === 'criteria'
      ? 'criteria'
      : tabParam === 'schedules' && !isReadOnly
        ? 'schedules'
        : 'reviews';
  const setActiveTab = (tab: NurseTab) => {
    const next = new URLSearchParams(searchParams);
    next.set('tab', tab);
    setSearchParams(next, { replace: true }); // tab toggles shouldn't pile up history
  };
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>('all');
  const [deptFilter, setDeptFilter] = useState<string>('all');
  const [reviews, setReviews] = useState<AssessmentReviewOut[]>([]);
  const [feedbackRows, setFeedbackRows] = useState<RoutingFeedbackOut[]>([]);
  const [departments, setDepartments] = useState<DepartmentOut[]>([]);
  const [authError, setAuthError] = useState<string | null>(null);
  const [reviewActionLoading, setReviewActionLoading] = useState<string | null>(null);
  const [slipQuery, setSlipQuery] = useState('');
  const [reviewDataLoading, setReviewDataLoading] = useState(true);

  const [selectedReview, setSelectedReview] = useState<AssessmentReviewOut | null>(null);
  const [sessionMessages, setSessionMessages] = useState<MessageOut[]>([]);
  const [sessionMessagesLoading, setSessionMessagesLoading] = useState(false);
  // One review is edited at a time, so a single set of draft fields is enough.
  const [modalTab, setModalTab] = useState<ReviewModalTab>('assessment');
  const [editComplaint, setEditComplaint] = useState('');
  const [editNote, setEditNote] = useState('');
  const [editDeptId, setEditDeptId] = useState('');
  const [editReason, setEditReason] = useState('');
  const [editScore, setEditScore] = useState('');
  // Confirm-before-publish: assigning moves a real patient in the hospital's
  // live queue and clears their previous one, so it gets its own step.
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [sbarDraft, setSbarDraft] = useState<SbarFields | null>(null);
  const [sbarLoading, setSbarLoading] = useState(false);
  // Errors from the dialog must render INSIDE it — the page-level authError
  // sits above the review modal and is invisible behind the overlay.
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [assignResult, setAssignResult] = useState<AssessmentReviewOut | null>(null);

  const staffEmail = getAdminEmail() ?? t('loginNurseTab');
  const loginPathForRole = () => (getAdminRole() === 'nurse' ? '/login/nurse' : '/login/admin');

  const loadReviewData = async (status: ReviewFilter) => {
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
      // Only a stale token warrants a logout. A 403 means the role lacks the
      // permission — logging out would strand them at a login their role
      // cannot use, so surface it as an error instead.
      if (
        message.includes('401') ||
        message.toLowerCase().includes('token') ||
        message.toLowerCase().includes('unauthorized')
      ) {
        const loginPath = loginPathForRole();
        api.adminLogout();
        navigate(loginPath, { replace: true });
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
    const loginPath = loginPathForRole(); // read the role before it is cleared
    api.adminLogout();
    navigate(loginPath, { replace: true });
  };

  // One button: an unchanged department confirms/approves; a changed one is
  // recorded as a correction + HIS reroute. Complaint/note edits go either way.
  const isReroute = (review: AssessmentReviewOut) =>
    Boolean(editDeptId) && editDeptId !== review.proposed_department_id;

  /** Step 1: show the nurse exactly what will be sent to the hospital. */
  const handleOpenConfirm = async (review: AssessmentReviewOut) => {
    setConfirmOpen(true);
    setConfirmError(null);
    setAssignResult(null);
    setSbarLoading(true);
    try {
      const draft = await api.previewReviewSbar(review.assessment_id, {
        department_id: editDeptId || null,
        chief_complaint: editComplaint.trim() || null,
        illness_note: editNote.trim() || null,
      });
      setSbarDraft(draft);
    } catch (err) {
      // The handover can still be sent — the server rebuilds it when the
      // request omits `sbar` — so this is a warning, not a blocker.
      setSbarDraft(null);
      setConfirmError(err instanceof Error ? err.message : t('error'));
    } finally {
      setSbarLoading(false);
    }
  };

  const handleCloseConfirm = () => {
    setConfirmOpen(false);
    setSbarDraft(null);
    setConfirmError(null);
    setAssignResult(null);
  };

  /** Step 2: publish. The response carries the hospital's outcome — the queue
   *  number the nurse reads to the patient — so it must not be discarded. */
  const handleConfirm = async (review: AssessmentReviewOut) => {
    setReviewActionLoading(review.assessment_id);
    setConfirmError(null);
    const narrative = {
      ai_assessment_score: editScore ? Number(editScore) : null,
      chief_complaint: editComplaint.trim() || null,
      illness_note: editNote.trim() || null,
      sbar: sbarDraft,
    };
    const rerouted = isReroute(review);
    try {
      const updated = rerouted
        ? await api.correctAssessmentReview(review.assessment_id, {
            confirmed_department_id: editDeptId,
            reason: editReason.trim() || null,
            ...narrative,
          })
        : await api.approveAssessmentReview(review.assessment_id, narrative);
      setAssignResult(updated);
      // Refresh behind the dialog; the nurse dismisses once they've read the
      // queue number out.
      await loadReviewData(reviewFilter);
    } catch (err) {
      setConfirmError(err instanceof Error ? err.message : t('error'));
    } finally {
      setReviewActionLoading(null);
    }
  };

  const handleFinishConfirm = () => {
    handleCloseConfirm();
    setSelectedReview(null);
    setSessionMessages([]);
  };

  const handleOpenReview = async (review: AssessmentReviewOut) => {
    setSelectedReview(review);
    setModalTab('assessment');
    setEditComplaint(review.chief_complaint ?? review.ai_chief_complaint ?? '');
    setEditNote(review.illness_note ?? review.ai_illness_note ?? '');
    setEditDeptId(review.proposed_department_id ?? '');
    setEditReason('');
    setEditScore(review.ai_assessment_score ? String(review.ai_assessment_score) : '');
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

  /** Human name for a department id, from the list already loaded. */
  const departmentLabel = (departmentId?: string | null) => {
    const dept = departments.find((d) => d.id === departmentId);
    if (!dept) return '—';
    return language === 'th' ? dept.name_th ?? dept.name_en : dept.name_en;
  };

  const reviewDeptLabel = (review: AssessmentReviewOut) =>
    language === 'th'
      ? review.proposed_department_name_th ?? review.proposed_department_name_en ?? '—'
      : review.proposed_department_name_en ?? '—';

  const confirmedDeptLabel = (review: AssessmentReviewOut) =>
    language === 'th'
      ? review.confirmed_department_name_th ?? review.confirmed_department_name_en ?? null
      : review.confirmed_department_name_en ?? null;

  const filteredReviews = useMemo(() => {
    const key = slipSearchKey(slipQuery);
    return reviews.filter((review) => {
      if (key && !slipSearchKey(slipCode(review.session_id)).includes(key)) {
        return false;
      }
      if (deptFilter !== 'all') {
        // Where the patient actually goes: nurse-confirmed when present,
        // otherwise the AI-proposed department.
        const effectiveDept =
          review.confirmed_department_id ?? review.proposed_department_id;
        if (effectiveDept !== deptFilter) return false;
      }
      return true;
    });
  }, [reviews, slipQuery, deptFilter]);

  const complaintPreview = (review: AssessmentReviewOut) =>
    review.chief_complaint ?? review.ai_chief_complaint ?? '—';

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
          {/* Schedule management is all writes — viewers have no use for it. */}
          {!isReadOnly && (
            <button
              type="button"
              className={`nurse-tab-btn ${activeTab === 'schedules' ? 'active' : ''}`}
              onClick={() => setActiveTab('schedules')}
            >
              {t('scheduleTabDoctors')}
            </button>
          )}
          {/* Read-only rule book — the criteria the booth decides on, with
              the MFU manual citations. The endpoint already allows nurses;
              without this tab the page built for them was unreachable. */}
          <button
            type="button"
            className={`nurse-tab-btn ${activeTab === 'criteria' ? 'active' : ''}`}
            onClick={() => setActiveTab('criteria')}
          >
            📖 {t('criteriaBookTab')}
          </button>
        </div>

        {authError ? <p className="error-text">{authError}</p> : null}

        {activeTab === 'schedules' && (
          <DoctorScheduleManager departments={departments} />
        )}

        {activeTab === 'criteria' && <CriteriaBook />}

        {activeTab === 'reviews' && <div className="admin-toolbar nurse-toolbar">
          <input
            type="search"
            className="admin-search nurse-slip-search"
            placeholder={t('nurseSlipSearchPlaceholder')}
            value={slipQuery}
            onChange={(e) => setSlipQuery(e.target.value)}
            aria-label={t('nurseSlipSearchPlaceholder')}
          />
          <div className="chip-group" role="group" aria-label={t('nurseFilterLabel')}>
            {(['all', 'pending', 'reviewed'] as const).map((filter) => (
              <button
                key={filter}
                type="button"
                className={`filter-chip tone-neutral ${reviewFilter === filter ? 'active' : ''}`}
                onClick={() => setReviewFilter(filter)}
              >
                {filter === 'all'
                  ? t('filterAll')
                  : filter === 'pending'
                    ? t('review_pending')
                    : t('nurseFilterReviewed')}
              </button>
            ))}
          </div>
          <select
            className="nurse-dept-filter"
            value={deptFilter}
            onChange={(e) => setDeptFilter(e.target.value)}
            aria-label={t('nurseDeptFilterLabel')}
          >
            <option value="all">{t('nurseDeptFilterAll')}</option>
            {departments.map((d) => (
              <option key={d.id} value={d.id}>
                {language === 'th' ? d.name_th ?? d.name_en : d.name_en}
              </option>
            ))}
          </select>
        </div>}

        {/* ── Review cards ── */}
        {activeTab === 'reviews' && (reviewDataLoading ? (
          <p className="muted">{t('loading')}</p>
        ) : filteredReviews.length === 0 ? (
          <p className="muted">{t('adminNoReviews')}</p>
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
                      <code className="nurse-slip-code" title={t('nurseSlipCodeLabel')}>
                        {slipCode(review.session_id)}
                      </code>
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
                    <div className="nurse-card-meta-item nurse-card-complaint">
                      <span className="nurse-card-dept-label">{t('nurseChiefComplaint')}</span>
                      <span className="nurse-card-dept-value">{complaintPreview(review)}</span>
                    </div>
                    <div className="nurse-card-meta-item">
                      <span className="nurse-card-dept-label">{t('nursePatientName')}</span>
                      <span className="nurse-card-dept-value">
                        {review.patient_name || '—'}
                      </span>
                    </div>
                    <div className="nurse-card-meta-item">
                      <span className="nurse-card-dept-label">{t('nurseVisitLabel')}</span>
                      <span className="nurse-card-dept-value">
                        {review.visit_id ? <code>{review.visit_id}</code> : t('nurseVisitNotLinked')}
                      </span>
                    </div>
                    {review.his_routing_status ? (
                      <div className="nurse-card-meta-item">
                        <span className="nurse-card-dept-label">HIS</span>
                        <span className="nurse-card-dept-value">
                          {review.his_routing_status === 'pushed'
                            ? t('nurseHisPublished')
                            : t('nurseHisPushFailed')}
                        </span>
                      </div>
                    ) : null}
                  </div>

                  {(review.disposition_reasons?.length ?? 0) > 0 && (
                    <details className="nurse-ai-reasoning">
                      <summary>{t('aiReasoningTitle')}</summary>
                      <ul>
                        {review.disposition_reasons!.map((reason) => (
                          <li key={reason.rule_id}>
                            {language === 'th' ? reason.text_th : reason.text_en}
                            {reason.citation ? (
                              <span className="muted"> — {reason.citation}</span>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}

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
                    {slipCode(selectedReview.session_id)}
                  </h2>
                  <code className="nurse-session-code">{selectedReview.session_id}</code>
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

              <div className="nurse-modal-tab-bar" role="tablist">
                <button
                  type="button"
                  role="tab"
                  aria-selected={modalTab === 'assessment'}
                  className={`nurse-tab-btn ${modalTab === 'assessment' ? 'active' : ''}`}
                  onClick={() => setModalTab('assessment')}
                >
                  {t('nurseAssessmentTab')}
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={modalTab === 'conversation'}
                  className={`nurse-tab-btn ${modalTab === 'conversation' ? 'active' : ''}`}
                  onClick={() => setModalTab('conversation')}
                >
                  {t('nurseConversationTitle')}
                  <span className="nurse-conv-panel-count">
                    {sessionMessagesLoading ? '…' : ` ${sessionMessages.length}`}
                  </span>
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={modalTab === 'history'}
                  className={`nurse-tab-btn ${modalTab === 'history' ? 'active' : ''}`}
                  onClick={() => setModalTab('history')}
                >
                  {t('nurseHistoryTab')}
                </button>
              </div>

              <div className="nurse-review-modal-body nurse-review-modal-tabbed">
                {modalTab === 'assessment' && (
                  <section className="nurse-assessment-panel">
                    <p className="nurse-review-section-title">{t('nurseMeasuredAtBooth')}</p>
                    {(selectedReview.missing_vitals?.length ?? 0) > 0 && (
                      <p className="vitals-warning" role="alert">
                        {'⚠ '}
                        {t('nurseMissingVitals')}
                        {': '}
                        {selectedReview.missing_vitals!
                          .map((key) => t(`nurseMissingVitalName_${key}`, { defaultValue: key }))
                          .join(', ')}
                      </p>
                    )}
                    {Object.keys(selectedReview.rejected_vitals ?? {}).length > 0 && (
                      <p className="vitals-warning" role="alert">
                        {'⚠ '}
                        {t('nurseRejectedVitals')}
                        {': '}
                        {Object.entries(selectedReview.rejected_vitals!)
                          .map(([key, hit]) =>
                            `${t(`nurseMissingVitalName_${key}`, { defaultValue: key })} ${hit.value}`,
                          )
                          .join(', ')}
                      </p>
                    )}
                    <div className="nurse-vitals-grid">
                      <div className="nurse-vital-item">
                        <span className="nurse-card-dept-label">{t('nurseVitalBp')}</span>
                        <RejectedVitalValue
                          rejected={selectedReview.rejected_vitals}
                          vitals={['sbp', 'dbp']}
                          fallback={
                            selectedReview.vitals?.systolic && selectedReview.vitals?.diastolic
                              ? `${selectedReview.vitals.systolic}/${selectedReview.vitals.diastolic}`
                              : '—'
                          }
                        />
                      </div>
                      <div className="nurse-vital-item">
                        <span className="nurse-card-dept-label">{t('nurseVitalPulse')}</span>
                        <RejectedVitalValue
                          rejected={selectedReview.rejected_vitals}
                          vitals={['hr']}
                          fallback={formatNumber(selectedReview.vitals?.pulse_bpm)}
                        />
                      </div>
                      <div className="nurse-vital-item">
                        <span className="nurse-card-dept-label">{t('nurseVitalWeight')}</span>
                        <RejectedVitalValue
                          rejected={selectedReview.rejected_vitals}
                          vitals={['weight']}
                          fallback={formatNumber(selectedReview.vitals?.weight_kg)}
                        />
                      </div>
                      <div className="nurse-vital-item">
                        <span className="nurse-card-dept-label">{t('nurseVitalHeight')}</span>
                        <RejectedVitalValue
                          rejected={selectedReview.rejected_vitals}
                          vitals={['height']}
                          fallback={formatNumber(selectedReview.vitals?.height_cm)}
                        />
                      </div>
                      <div className="nurse-vital-item">
                        <span className="nurse-card-dept-label">BMI</span>
                        <strong>
                          {formatBmi(selectedReview.vitals?.weight_kg, selectedReview.vitals?.height_cm)}
                        </strong>
                      </div>
                      <div className="nurse-vital-item">
                        <span className="nurse-card-dept-label">{t('nurseVitalTemp')}</span>
                        <RejectedVitalValue
                          rejected={selectedReview.rejected_vitals}
                          vitals={['temp']}
                          fallback={formatNumber(selectedReview.vitals?.temperature, 1)}
                        />
                      </div>
                      <div className="nurse-vital-item">
                        <span className="nurse-card-dept-label">{t('nursePatientName')}</span>
                        <strong>{selectedReview.patient_name || '—'}</strong>
                      </div>
                      <div className="nurse-vital-item">
                        <span className="nurse-card-dept-label">{t('nurseVisitLabel')}</span>
                        <strong>
                          {selectedReview.visit_id ? (
                            <code>{selectedReview.visit_id}</code>
                          ) : (
                            t('nurseVisitNotLinked')
                          )}
                        </strong>
                      </div>
                    </div>

                    <p className="nurse-review-section-title">{t('nursePatientFollowUp')}</p>
                    <p className="nurse-follow-up-note">
                      {selectedReview.patient_follow_up || '—'}
                    </p>

                    <p className="nurse-review-section-title">{t('nurseAssessmentSection')}</p>
                    {selectedReview.status === 'pending' && !isReadOnly ? (
                      <>
                        <p className="muted nurse-narrative-hint">{t('nurseNarrativeHint')}</p>
                        <label className="nurse-modal-field">
                          <span>{t('nurseChiefComplaint')}</span>
                          <textarea
                            className="nurse-narrative-input"
                            rows={2}
                            value={editComplaint}
                            onChange={(e) => setEditComplaint(e.target.value)}
                          />
                        </label>
                        <label className="nurse-modal-field">
                          <span>{t('nurseIllnessNote')}</span>
                          <textarea
                            className="nurse-narrative-input"
                            rows={2}
                            value={editNote}
                            onChange={(e) => setEditNote(e.target.value)}
                          />
                        </label>
                        <label className="nurse-modal-field">
                          <span>{t('department')}</span>
                          <select
                            className="nurse-dept-select"
                            value={editDeptId}
                            onChange={(e) => setEditDeptId(e.target.value)}
                          >
                            {!selectedReview.proposed_department_id && (
                              <option value="">{t('adminSelectDepartment')}</option>
                            )}
                            {departments
                              .filter(
                                (dept) =>
                                  dept.kind === 'opd' ||
                                  dept.id === selectedReview.proposed_department_id,
                              )
                              // AI-assessed department first; it is also the
                              // pre-selected value, so the dropdown opens on it.
                              .sort((a, b) =>
                                (a.id === selectedReview.proposed_department_id ? 0 : 1) -
                                (b.id === selectedReview.proposed_department_id ? 0 : 1))
                              .map((dept) => (
                                <option key={dept.id} value={dept.id}>
                                  {language === 'th' ? dept.name_th ?? dept.name_en : dept.name_en}
                                </option>
                              ))}
                          </select>
                        </label>
                        {editDeptId && editDeptId !== selectedReview.proposed_department_id ? (
                          <input
                            type="text"
                            className="nurse-reason-input"
                            placeholder={t('adminCorrectionReasonPlaceholder')}
                            value={editReason}
                            onChange={(e) => setEditReason(e.target.value)}
                          />
                        ) : null}

                        {(selectedReview.disposition_reasons?.length ?? 0) > 0 && (
                          <details className="nurse-ai-reasoning">
                            <summary>{t('aiReasoningTitle')}</summary>
                            <ul>
                              {selectedReview.disposition_reasons!.map((reason) => (
                                <li key={reason.rule_id}>
                                  {language === 'th' ? reason.text_th : reason.text_en}
                                  {reason.citation ? (
                                    <span className="muted"> — {reason.citation}</span>
                                  ) : null}
                                </li>
                              ))}
                            </ul>
                          </details>
                        )}

                        <label className="nurse-score-field nurse-modal-field">
                          <span>{t('aiAssessmentScore')}</span>
                          <select
                            className="nurse-score-select"
                            value={editScore}
                            onChange={(e) => setEditScore(e.target.value)}
                          >
                            <option value="">{t('aiAssessmentScorePlaceholder')}</option>
                            {Array.from({ length: 10 }, (_, index) => index + 1).map((score) => (
                              <option key={score} value={score}>
                                {score}/10
                              </option>
                            ))}
                          </select>
                        </label>

                        <div className="nurse-review-modal-actions">
                          <button
                            type="button"
                            className="nurse-approve-btn"
                            disabled={reviewActionLoading === selectedReview.assessment_id}
                            onClick={() => void handleOpenConfirm(selectedReview)}
                          >
                            <span aria-hidden="true">{'✓'}</span>
                            {editDeptId && editDeptId !== selectedReview.proposed_department_id
                              ? t('nurseConfirmReroute')
                              : t('nurseConfirmPublish')}
                          </button>
                        </div>
                      </>
                    ) : (
                      <div className="nurse-review-facts">
                        <div>
                          <span className="nurse-card-dept-label">{t('nurseChiefComplaint')}</span>
                          <strong>
                            {selectedReview.chief_complaint ?? selectedReview.ai_chief_complaint ?? '—'}
                          </strong>
                        </div>
                        <div>
                          <span className="nurse-card-dept-label">{t('nurseIllnessNote')}</span>
                          <strong>
                            {selectedReview.illness_note ?? selectedReview.ai_illness_note ?? '—'}
                          </strong>
                        </div>
                        <div>
                          <span className="nurse-card-dept-label">{t('department')}</span>
                          <strong>
                            {confirmedDeptLabel(selectedReview) ?? reviewDeptLabel(selectedReview)}
                          </strong>
                        </div>
                        {selectedReview.his_routing_status ? (
                          <div>
                            <span className="nurse-card-dept-label">HIS</span>
                            <strong>
                              {selectedReview.his_routing_status === 'pushed'
                                ? t('nurseHisPublished')
                                : t('nurseHisPushFailed')}
                            </strong>
                          </div>
                        ) : null}
                        {selectedReview.ai_assessment_score ? (
                          <div>
                            <span className="nurse-card-dept-label">{t('aiAssessmentScore')}</span>
                            <strong>
                              {selectedReview.ai_assessment_score}/{selectedReview.ai_assessment_scale}
                            </strong>
                          </div>
                        ) : null}
                      </div>
                    )}
                  </section>
                )}

                {modalTab === 'conversation' && (
                  <section className="nurse-review-transcript-panel">
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
                )}

                {modalTab === 'history' && (
                  <section className="nurse-assessment-panel">
                    <p className="nurse-review-section-title">{t('hdbGroupHistory')}</p>
                    {selectedReview.patient_history ? (
                      <div className="nurse-review-facts">
                        {selectedReview.patient_hn ? (
                          <div>
                            <span className="nurse-card-dept-label">HN</span>
                            <strong><code>{selectedReview.patient_hn}</code></strong>
                          </div>
                        ) : null}
                        <div>
                          <span className="nurse-card-dept-label">{t('hdbSmokingAlcohol')}</span>
                          <strong>{selectedReview.patient_history.smoking_alcohol || '—'}</strong>
                        </div>
                        <div>
                          <span className="nurse-card-dept-label">{t('hdbAllergies')}</span>
                          <strong>{selectedReview.patient_history.allergies || '—'}</strong>
                        </div>
                        <div>
                          <span className="nurse-card-dept-label">{t('hdbChronicConditions')}</span>
                          <strong>{selectedReview.patient_history.chronic_conditions || '—'}</strong>
                        </div>
                        <div>
                          <span className="nurse-card-dept-label">{t('hdbPastSurgeries')}</span>
                          <strong>{selectedReview.patient_history.past_surgeries || '—'}</strong>
                        </div>
                        <div>
                          <span className="nurse-card-dept-label">{t('hdbFamilyHistory')}</span>
                          <strong>{selectedReview.patient_history.family_history || '—'}</strong>
                        </div>
                        <div>
                          <span className="nurse-card-dept-label">{t('hdbHistoryRecordedAt')}</span>
                          <strong>
                            {formatDateAbsolute(selectedReview.patient_history.recorded_at ?? null)}
                          </strong>
                        </div>
                      </div>
                    ) : (
                      <p className="muted">{t('nurseHistoryNone')}</p>
                    )}
                  </section>
                )}
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
      {/* Confirm-before-publish. Reuses the .tm-confirm-* overlay (z-index
          1000) which already stacks over .nurse-review-modal (80), so this
          needs no new overlay CSS. */}
      {confirmOpen && selectedReview ? (
        <div className="tm-confirm-overlay" role="alertdialog" aria-modal="true">
          <div className="tm-confirm-box nurse-sbar-box">
            {assignResult ? (
              <ConfirmResult review={assignResult} onDone={handleFinishConfirm} />
            ) : (
              <>
                <h3>
                  {isReroute(selectedReview)
                    ? t('nurseConfirmReroute')
                    : t('nurseConfirmPublish')}
                </h3>
                <p className="nurse-sbar-warning">{t('nurseAssignWarning')}</p>
                <p className="nurse-sbar-dept">
                  {departmentLabel(editDeptId || selectedReview.proposed_department_id)}
                  {selectedReview.patient_name ? ` · ${selectedReview.patient_name}` : ''}
                  {selectedReview.visit_id ? ` · VN ${selectedReview.visit_id}` : ''}
                </p>

                <p className="nurse-sbar-hint">{t('nurseSbarHint')}</p>
                {sbarLoading ? (
                  <p>{t('loading')}</p>
                ) : (
                  <div className="nurse-sbar-fields">
                    {SBAR_FIELDS.map((field) => (
                      <label key={field}>
                        <span>{t(`nurseSbar_${field}`)}</span>
                        <textarea
                          rows={field === 'assessment_equipment' ? 1 : 2}
                          value={sbarDraft?.[field] ?? ''}
                          placeholder={
                            field === 'assessment_equipment'
                              ? t('nurseSbarEquipmentPlaceholder')
                              : undefined
                          }
                          onChange={(event) =>
                            setSbarDraft((prev: SbarFields | null) => ({
                              ...(prev ?? {}),
                              [field]: event.target.value,
                            }))
                          }
                        />
                      </label>
                    ))}
                  </div>
                )}

                {confirmError ? <p className="error-text">{confirmError}</p> : null}

                <div className="tm-confirm-actions">
                  <button type="button" onClick={handleCloseConfirm}>
                    {t('cancel')}
                  </button>
                  <button
                    type="button"
                    className="nurse-approve-btn"
                    disabled={reviewActionLoading === selectedReview.assessment_id}
                    onClick={() => void handleConfirm(selectedReview)}
                  >
                    {t('nurseAssignSend')}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      ) : null}
    </Layout>
  );
}
