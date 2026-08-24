import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { BookOpen, ChartBar, ClipboardText, WarningCircle, X } from '@phosphor-icons/react';
import { api, type MessageOut } from '../api';
import { getAdminEmail, getAdminRole, getAdminToken } from '../api/client';
import { Layout } from '../components/Layout';
import { MessageBubble } from '../components/MessageBubble';
import { CriteriaBook } from '../components/CriteriaBook';
import { TriageDashboard } from '../components/TriageDashboard';
import { StaffNav, type StaffNavItem } from '../components/staff/StaffNav';
import { useLanguage } from '../hooks/useSession';
import { slipCode, slipSearchKey } from '../utils/slipCode';
import type {
  AssessmentReviewOut,
  SbarFields,
  DepartmentOut,
  RejectedVital,
} from '../api/types';

type NurseSection = 'queue' | 'dashboard' | 'criteria';
type ReviewTab = 'assessment' | 'conversation' | 'history';
type ReviewFilter = 'all' | 'pending' | 'reviewed';
/** The dialog is one surface with three steps — never a dialog over a dialog. */
type DialogStep = 'review' | 'confirm' | 'result';

const AUTO_REFRESH_MS = 30_000;

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

function minutesSince(iso: string): number {
  return Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
}

/**
 * The engine's MOPH level. The number is not decoration: levels 1 and 2 sit
 * at ΔE 13 for normal colour vision, so the colour alone cannot carry which
 * one this is. Colour reinforces, the digit states.
 */
function TriageBadge({ level, size = 'md' }: { level?: number | null; size?: 'md' | 'lg' }) {
  const { t } = useTranslation();
  if (!level) {
    return <span className={`triage-badge triage-badge-none triage-badge-${size}`}>—</span>;
  }
  return (
    <span
      className={`triage-badge triage-level-${level} triage-badge-${size}`}
      title={t(`triageLevelName_${level}`)}
    >
      <span className="triage-badge-num">{level}</span>
      {size === 'lg' ? (
        <span className="triage-badge-name">{t(`triageLevelName_${level}`)}</span>
      ) : null}
    </span>
  );
}

/** Where a vital came from — a device reading and a patient-typed number
 *  must not look identical to the nurse. HIS-carried values show no tag. */
function VitalSource({ sources, keys }: { sources?: Record<string, string> | null; keys: string[] }) {
  const { t } = useTranslation();
  const src = keys.map((k) => sources?.[k]).find(Boolean);
  if (!src) return null;
  if (src === 'device') return <span className="vital-source device">{t('nurseSourceDevice')}</span>;
  if (src === 'patient_input' || src === 'manual') {
    return <span className="vital-source patient">{t('nurseSourcePatient')}</span>;
  }
  return null;
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
  if (!hit) return <strong className="vital-value">{fallback}</strong>;
  return (
    <strong className="vital-value vital-rejected" title={t('nurseRejectedVitals')}>
      <s>{hit.value}</s>
      <span className="vital-rejected-note">
        {t(`nurseRejectedSource_${hit.source ?? 'reported'}`, { defaultValue: '' })}
        {', '}
        {t(`nurseRejectedReason_${hit.reason}`, { defaultValue: hit.reason })}
      </span>
    </strong>
  );
}

function VitalCell({
  label,
  children,
  source,
}: {
  label: React.ReactNode;
  children: React.ReactNode;
  source?: React.ReactNode;
}) {
  return (
    <div className="vital-cell">
      <span className="vital-label">
        {label}
        {source}
      </span>
      {children}
    </div>
  );
}

/**
 * What the hospital said. Branch on `his_routing_status`, NOT on the HTTP
 * status: approve/correct return 200 whatever the HIS did, so the outcome
 * only exists in the body.
 */
function AssignResult({ review, onDone }: { review: AssessmentReviewOut; onDone: () => void }) {
  const { t } = useTranslation();
  const status = review.his_routing_status ?? 'unknown';
  const detail = review.his_routing_message_th;

  if (status === 'pushed') {
    return (
      <div className="assign-result">
        <p className="assign-result-kicker">{t('nurseAssignQueued')}</p>
        {review.his_queue_number ? (
          <>
            <p className="assign-queue-number">{review.his_queue_number}</p>
            <p className="assign-result-hint">{t('nurseAssignGiveNumber')}</p>
          </>
        ) : (
          // 409 without a result body: the patient IS queued, but the hospital
          // did not tell us the number (our change request 7).
          <p className="alert-note alert-note-warning">{t('nurseAssignNoNumber')}</p>
        )}
        <button type="button" className="primary-btn" onClick={onDone}>
          {t('close')}
        </button>
      </div>
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
    <div className="assign-result">
      <p className="assign-result-kicker">{t('nurseAssignNotQueued')}</p>
      <p className="alert-note alert-note-danger">
        <WarningCircle size={18} weight="fill" aria-hidden="true" />
        {messages[status] ?? t('nurseHisPushFailed')}
      </p>
      {detail ? <p className="muted">{detail}</p> : null}
      <button type="button" className="primary-btn" onClick={onDone}>
        {t('close')}
      </button>
    </div>
  );
}

export function NursePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { language, setLanguage } = useLanguage();
  // Ops staff can reach this portal too; viewers get the read-only view and
  // must be sent back to their own login, not the nurse one.
  const isReadOnly = getAdminRole() === 'viewer';
  // The section lives in the URL so the floating shortcut can land on a
  // specific one — /nurse and /nurse?tab=dashboard share a route element, so
  // nothing remounts on a same-route jump and local state would stay stale.
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get('tab');
  const activeSection: NurseSection =
    tabParam === 'criteria' ? 'criteria' : tabParam === 'dashboard' ? 'dashboard' : 'queue';
  const setActiveSection = (tab: NurseSection) => {
    const next = new URLSearchParams(searchParams);
    next.set('tab', tab);
    setSearchParams(next, { replace: true }); // section toggles shouldn't pile up history
  };

  // Pending is the working set. The old default was "all", which buried the
  // work the nurse opened the page to do under everything already done.
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>('pending');
  const [deptFilter, setDeptFilter] = useState<string>('all');
  const [reviews, setReviews] = useState<AssessmentReviewOut[]>([]);
  const [departments, setDepartments] = useState<DepartmentOut[]>([]);
  const [authError, setAuthError] = useState<string | null>(null);
  const [reviewActionLoading, setReviewActionLoading] = useState<string | null>(null);
  const [slipQuery, setSlipQuery] = useState('');
  const [reviewDataLoading, setReviewDataLoading] = useState(true);
  // Recomputes the "waiting" column without refetching.
  const [, setClockTick] = useState(0);

  const [selectedReview, setSelectedReview] = useState<AssessmentReviewOut | null>(null);
  const [sessionMessages, setSessionMessages] = useState<MessageOut[]>([]);
  const [sessionMessagesLoading, setSessionMessagesLoading] = useState(false);
  // One review is edited at a time, so a single set of draft fields is enough.
  const [reviewTab, setReviewTab] = useState<ReviewTab>('assessment');
  const [step, setStep] = useState<DialogStep>('review');
  const [editComplaint, setEditComplaint] = useState('');
  const [editNote, setEditNote] = useState('');
  const [editDeptId, setEditDeptId] = useState('');
  const [editReason, setEditReason] = useState('');
  // Nurse-entered VN, shown only when the linked HN has no visit passthrough.
  const [editVisitId, setEditVisitId] = useState('');
  const [editScore, setEditScore] = useState('');
  const [sbarDraft, setSbarDraft] = useState<SbarFields | null>(null);
  const [sbarLoading, setSbarLoading] = useState(false);
  // Errors from the confirm step must render INSIDE the dialog — a page-level
  // error sits behind the overlay and is invisible.
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [assignResult, setAssignResult] = useState<AssessmentReviewOut | null>(null);

  const staffEmail = getAdminEmail() ?? t('loginNurseTab');
  const loginPathForRole = () => (getAdminRole() === 'nurse' ? '/login/nurse' : '/login/admin');

  const loadReviewData = async (status: ReviewFilter) => {
    if (!getAdminToken()) return;
    setReviewDataLoading(true);
    setAuthError(null);
    try {
      setReviews(await api.listAssessmentReviews(status));
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void loadReviewData(reviewFilter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reviewFilter]);

  // A confirmation queue that only updates when someone clicks refresh is a
  // queue that is quietly wrong. Skip while a case is open — refetching under
  // the nurse would swap the row they are reading.
  useEffect(() => {
    if (activeSection !== 'queue') return undefined;
    const timer = window.setInterval(() => {
      setClockTick((n) => n + 1);
      if (document.visibilityState !== 'visible' || selectedReview) return;
      void loadReviewData(reviewFilter);
    }, AUTO_REFRESH_MS);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSection, reviewFilter, selectedReview]);

  useEffect(() => {
    if (!selectedReview) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [selectedReview]);

  // Escape closes the dialog — a modal without it traps keyboard users.
  useEffect(() => {
    if (!selectedReview) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (step === 'confirm') setStep('review');
      else if (step === 'review') handleCloseReview();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedReview, step]);

  const handleLogout = () => {
    const loginPath = loginPathForRole(); // read the role before it is cleared
    api.adminLogout();
    navigate(loginPath, { replace: true });
  };

  // One button: an unchanged department confirms/approves; a changed one is
  // recorded as a correction + HIS reroute. Complaint/note edits go either way.
  const isReroute = (review: AssessmentReviewOut) =>
    Boolean(editDeptId) && editDeptId !== review.proposed_department_id;

  /** Step 1 → 2: show the nurse exactly what will be sent to the hospital. */
  const handleOpenConfirm = async (review: AssessmentReviewOut) => {
    setStep('confirm');
    setDialogError(null);
    setAssignResult(null);
    setSbarLoading(true);
    try {
      setSbarDraft(
        await api.previewReviewSbar(review.assessment_id, {
          department_id: editDeptId || null,
          chief_complaint: editComplaint.trim() || null,
          illness_note: editNote.trim() || null,
        }),
      );
    } catch (err) {
      // The handover can still be sent — the server rebuilds it when the
      // request omits `sbar` — so this is a warning, not a blocker.
      setSbarDraft(null);
      setDialogError(err instanceof Error ? err.message : t('error'));
    } finally {
      setSbarLoading(false);
    }
  };

  const handleBackToReview = () => {
    setStep('review');
    setEditVisitId('');
    setSbarDraft(null);
    setDialogError(null);
  };

  /** Step 2 → result. The response carries the hospital's outcome — the queue
   *  number the nurse reads to the patient — so it must not be discarded. */
  const handleConfirm = async (review: AssessmentReviewOut) => {
    setReviewActionLoading(review.assessment_id);
    setDialogError(null);
    const narrative = {
      ai_assessment_score: editScore ? Number(editScore) : null,
      chief_complaint: editComplaint.trim() || null,
      illness_note: editNote.trim() || null,
      sbar: sbarDraft,
      visit_id: editVisitId.trim() || null,
    };
    try {
      const updated = isReroute(review)
        ? await api.correctAssessmentReview(review.assessment_id, {
            confirmed_department_id: editDeptId,
            reason: editReason.trim() || null,
            ...narrative,
          })
        : await api.approveAssessmentReview(review.assessment_id, narrative);
      setAssignResult(updated);
      setStep('result');
      // Refresh behind the dialog; the nurse dismisses once they've read the
      // queue number out.
      await loadReviewData(reviewFilter);
    } catch (err) {
      setDialogError(err instanceof Error ? err.message : t('error'));
    } finally {
      setReviewActionLoading(null);
    }
  };

  const handleOpenReview = async (review: AssessmentReviewOut) => {
    setSelectedReview(review);
    setReviewTab('assessment');
    setStep('review');
    setDialogError(null);
    setAssignResult(null);
    setSbarDraft(null);
    setEditVisitId('');
    setEditComplaint(review.chief_complaint ?? review.ai_chief_complaint ?? '');
    setEditNote(review.illness_note ?? review.ai_illness_note ?? '');
    setEditDeptId(review.proposed_department_id ?? '');
    setEditReason('');
    setEditScore(review.ai_assessment_score ? String(review.ai_assessment_score) : '');
    setSessionMessages([]);
    setSessionMessagesLoading(true);
    try {
      setSessionMessages(await api.listMessages(review.session_id));
    } catch (err) {
      setDialogError(err instanceof Error ? err.message : t('error'));
    } finally {
      setSessionMessagesLoading(false);
    }
  };

  const handleCloseReview = () => {
    setSelectedReview(null);
    setSessionMessages([]);
    setStep('review');
  };

  const handleFinishAssign = () => {
    handleCloseReview();
    setAssignResult(null);
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

  const pendingCount = useMemo(
    () => reviews.filter((r) => r.status === 'pending').length,
    [reviews],
  );

  const filteredReviews = useMemo(() => {
    const key = slipSearchKey(slipQuery);
    return reviews
      .filter((review) => {
        if (key && !slipSearchKey(slipCode(review.session_id)).includes(key)) return false;
        if (deptFilter !== 'all') {
          // Where the patient actually goes: nurse-confirmed when present,
          // otherwise the AI-proposed department.
          const effectiveDept = review.confirmed_department_id ?? review.proposed_department_id;
          if (effectiveDept !== deptFilter) return false;
        }
        return true;
      })
      // Acuity first, then longest wait. The engine's level is the whole point
      // of the queue: a level 2 arriving now outranks a level 4 from an hour
      // ago, and the old created_at-only order hid exactly that.
      .sort((a, b) => {
        if (a.status !== b.status) return a.status === 'pending' ? -1 : 1;
        const levelA = a.triage_level ?? 99;
        const levelB = b.triage_level ?? 99;
        if (levelA !== levelB) return levelA - levelB;
        return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
      });
  }, [reviews, slipQuery, deptFilter]);

  const complaintPreview = (review: AssessmentReviewOut) =>
    review.chief_complaint ?? review.ai_chief_complaint ?? '—';

  const navItems: Array<StaffNavItem<NurseSection>> = [
    {
      id: 'queue',
      label: t('nurseSectionQueue'),
      icon: ClipboardText,
      badge: pendingCount,
    },
    { id: 'dashboard', label: t('nurseSectionDashboard'), icon: ChartBar },
    { id: 'criteria', label: t('criteriaBookTab'), icon: BookOpen },
  ];

  const sectionTitle: Record<NurseSection, string> = {
    queue: t('nurseSectionQueue'),
    dashboard: t('nurseSectionDashboard'),
    criteria: t('criteriaBookTitle'),
  };
  const sectionSubtitle: Record<NurseSection, string> = {
    queue: t('nurseQueueSubtitle'),
    dashboard: t('nurseDashboardSubtitle'),
    criteria: t('criteriaBookSubtitle'),
  };

  const canEdit = selectedReview?.status === 'pending' && !isReadOnly;

  return (
    <Layout
      language={language}
      onLanguageChange={setLanguage}
      showAdminLink={false}
      navTitle={t('nursePortalTitle')}
      staffEmail={staffEmail}
      onStaffLogout={handleLogout}
      sidebar={
        <StaffNav
          items={navItems}
          active={activeSection}
          onSelect={setActiveSection}
          title={t('nursePortalTitle')}
        />
      }
    >
      <section className="staff-page">
        <header className="staff-page-head">
          <div>
            <h1>{sectionTitle[activeSection]}</h1>
            <p className="muted">{sectionSubtitle[activeSection]}</p>
          </div>
          {activeSection === 'queue' && (
            <button
              type="button"
              className="secondary-btn"
              onClick={() => void loadReviewData(reviewFilter)}
              disabled={reviewDataLoading}
            >
              {t('adminRefresh')}
            </button>
          )}
        </header>

        {authError ? (
          <p className="alert-note alert-note-danger" role="alert">
            <WarningCircle size={18} weight="fill" aria-hidden="true" />
            {authError}
          </p>
        ) : null}

        {activeSection === 'criteria' && <CriteriaBook />}
        {activeSection === 'dashboard' && <TriageDashboard scope="nurse" />}

        {activeSection === 'queue' && (
          <>
            <div className="staff-toolbar">
              <input
                type="search"
                className="field-input staff-search"
                placeholder={t('nurseSlipSearchPlaceholder')}
                value={slipQuery}
                onChange={(e) => setSlipQuery(e.target.value)}
                aria-label={t('nurseSlipSearchPlaceholder')}
              />
              <div className="chip-group" role="group" aria-label={t('nurseFilterLabel')}>
                {(['pending', 'reviewed', 'all'] as const).map((filter) => (
                  <button
                    key={filter}
                    type="button"
                    className={`filter-chip ${reviewFilter === filter ? 'active' : ''}`}
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
                className="field-input"
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
            </div>

            {reviewDataLoading && reviews.length === 0 ? (
              <p className="muted">{t('loading')}</p>
            ) : filteredReviews.length === 0 ? (
              <div className="staff-empty">
                <p>{t('adminNoReviews')}</p>
              </div>
            ) : (
              <div className="table-wrap">
                <table className="staff-table queue-table">
                  <thead>
                    <tr>
                      <th scope="col" className="col-level">
                        {t('nurseColLevel')}
                      </th>
                      <th scope="col">{t('nurseColSlip')}</th>
                      <th scope="col">{t('nursePatientName')}</th>
                      <th scope="col">{t('nurseChiefComplaint')}</th>
                      <th scope="col">{t('department')}</th>
                      <th scope="col" className="col-num">
                        {t('nurseColWaiting')}
                      </th>
                      <th scope="col">{t('status')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredReviews.map((review) => {
                      const confirmed = confirmedDeptLabel(review);
                      const waited = minutesSince(review.created_at);
                      return (
                        <tr
                          key={review.id}
                          className={`queue-row ${review.triage_level && review.triage_level <= 2 ? 'row-urgent' : ''}`}
                          tabIndex={0}
                          role="button"
                          aria-label={t('nurseReviewCase')}
                          onClick={() => void handleOpenReview(review)}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter' || event.key === ' ') {
                              event.preventDefault();
                              void handleOpenReview(review);
                            }
                          }}
                        >
                          <td className="col-level">
                            <TriageBadge level={review.triage_level} />
                          </td>
                          <td>
                            <code className="slip-code">{slipCode(review.session_id)}</code>
                          </td>
                          <td>{review.patient_name || '—'}</td>
                          <td className="col-complaint">{complaintPreview(review)}</td>
                          <td>
                            {review.status === 'corrected' && confirmed
                              ? confirmed
                              : reviewDeptLabel(review)}
                          </td>
                          <td className="col-num">
                            {review.status === 'pending'
                              ? t('nurseWaitedMinutes', { n: waited })
                              : '—'}
                          </td>
                          <td>
                            <span className={`status-pill status-${review.status}`}>
                              {t(`review_${review.status}`)}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </section>

      {selectedReview && (
        <div
          className="dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="nurse-review-dialog-title"
        >
          <button
            type="button"
            className="dialog-backdrop"
            aria-label={t('close')}
            onClick={handleCloseReview}
          />
          <div className="dialog-card">
            {/* One header for all three steps — identity stays on screen while
                the body changes, so the nurse never loses which patient this
                is mid-confirmation. */}
            <header className="dialog-head">
              <div className="dialog-identity">
                <TriageBadge level={selectedReview.triage_level} size="lg" />
                <div>
                  <h2 id="nurse-review-dialog-title">
                    {selectedReview.patient_name || t('nurseHnNotLinked')}
                  </h2>
                  <p className="dialog-identity-meta">
                    <code className="slip-code">{slipCode(selectedReview.session_id)}</code>
                    {selectedReview.patient_hn ? (
                      <span>
                        {t('nurseHnLabel')} <code>{selectedReview.patient_hn}</code>
                      </span>
                    ) : null}
                    {selectedReview.visit_id ? (
                      <span>
                        VN <code>{selectedReview.visit_id}</code>
                      </span>
                    ) : null}
                  </p>
                </div>
              </div>
              <button
                type="button"
                className="icon-btn"
                onClick={handleCloseReview}
                aria-label={t('close')}
              >
                <X size={20} aria-hidden="true" />
              </button>
            </header>

            {step === 'review' && (
              <div className="dialog-tabs" role="tablist">
                {(['assessment', 'conversation', 'history'] as const).map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    role="tab"
                    aria-selected={reviewTab === tab}
                    className={`dialog-tab ${reviewTab === tab ? 'active' : ''}`}
                    onClick={() => setReviewTab(tab)}
                  >
                    {tab === 'assessment'
                      ? t('nurseAssessmentTab')
                      : tab === 'conversation'
                        ? t('nurseConversationTitle')
                        : t('nurseHistoryTab')}
                    {tab === 'conversation' ? (
                      <span className="dialog-tab-count">
                        {sessionMessagesLoading ? '…' : sessionMessages.length}
                      </span>
                    ) : null}
                  </button>
                ))}
              </div>
            )}

            <div className="dialog-body">
              {step === 'result' && assignResult ? (
                <AssignResult review={assignResult} onDone={handleFinishAssign} />
              ) : step === 'confirm' ? (
                <>
                  <p className="alert-note alert-note-warning">
                    <WarningCircle size={18} weight="fill" aria-hidden="true" />
                    {t('nurseAssignWarning')}
                  </p>
                  <div className="confirm-destination">
                    <span className="field-label">{t('nurseConfirmDestination')}</span>
                    <strong>
                      {departmentLabel(editDeptId || selectedReview.proposed_department_id)}
                    </strong>
                    {isReroute(selectedReview) ? (
                      <span className="confirm-reroute-tag">
                        {t('nurseConfirmRerouteFrom', {
                          from: reviewDeptLabel(selectedReview),
                        })}
                      </span>
                    ) : null}
                  </div>

                  {selectedReview.patient_hn && !selectedReview.visit_id ? (
                    <label className="field">
                      <span className="field-label">{t('nurseVnMissingLabel')}</span>
                      <input
                        type="text"
                        className="field-input"
                        value={editVisitId}
                        onChange={(e) => setEditVisitId(e.target.value)}
                        placeholder={t('nurseVnMissingPh')}
                        maxLength={64}
                      />
                    </label>
                  ) : null}

                  <p className="field-hint">{t('nurseSbarHint')}</p>
                  {sbarLoading ? (
                    <p className="muted">{t('loading')}</p>
                  ) : (
                    <div className="sbar-fields">
                      {SBAR_FIELDS.map((field) => (
                        <label key={field} className="field">
                          <span className="field-label">{t(`nurseSbar_${field}`)}</span>
                          <textarea
                            className="field-input field-textarea"
                            rows={field === 'assessment_equipment' ? 2 : 3}
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
                </>
              ) : reviewTab === 'assessment' ? (
                <>
                  {(selectedReview.missing_vitals?.length ?? 0) > 0 && (
                    <p className="alert-note alert-note-warning" role="alert">
                      <WarningCircle size={18} weight="fill" aria-hidden="true" />
                      {t('nurseMissingVitals')}
                      {': '}
                      {selectedReview.missing_vitals!
                        .map((key) => t(`nurseMissingVitalName_${key}`, { defaultValue: key }))
                        .join(', ')}
                    </p>
                  )}
                  {Object.keys(selectedReview.rejected_vitals ?? {}).length > 0 && (
                    <p className="alert-note alert-note-danger" role="alert">
                      <WarningCircle size={18} weight="fill" aria-hidden="true" />
                      {t('nurseRejectedVitals')}
                      {': '}
                      {Object.entries(selectedReview.rejected_vitals!)
                        .map(
                          ([key, hit]) =>
                            `${t(`nurseMissingVitalName_${key}`, { defaultValue: key })} ${hit.value}`,
                        )
                        .join(', ')}
                    </p>
                  )}

                  {/* The engine's own fired rules — the authoritative clinical
                      signal behind this level. Open by default: it was a
                      collapsed <details>, which hid the reasoning the nurse is
                      being asked to agree with. */}
                  {(selectedReview.disposition_reasons?.length ?? 0) > 0 && (
                    <section className="reasoning-block">
                      <h3 className="section-title">{t('aiReasoningTitle')}</h3>
                      <ul className="reasoning-list">
                        {selectedReview.disposition_reasons!.map((reason) => (
                          <li key={reason.rule_id}>
                            <span>{language === 'th' ? reason.text_th : reason.text_en}</span>
                            {reason.citation ? (
                              <cite className="reasoning-citation">{reason.citation}</cite>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    </section>
                  )}

                  <h3 className="section-title">{t('nurseMeasuredAtBooth')}</h3>
                  <div className="vitals-grid">
                    <VitalCell
                      label={t('nurseVitalBp')}
                      source={
                        <VitalSource
                          sources={selectedReview.vitals?.sources}
                          keys={['systolic', 'diastolic']}
                        />
                      }
                    >
                      <RejectedVitalValue
                        rejected={selectedReview.rejected_vitals}
                        vitals={['sbp', 'dbp']}
                        fallback={
                          selectedReview.vitals?.systolic && selectedReview.vitals?.diastolic
                            ? `${selectedReview.vitals.systolic}/${selectedReview.vitals.diastolic}`
                            : '—'
                        }
                      />
                    </VitalCell>
                    <VitalCell
                      label={t('nurseVitalPulse')}
                      source={
                        <VitalSource sources={selectedReview.vitals?.sources} keys={['pulse_bpm']} />
                      }
                    >
                      <RejectedVitalValue
                        rejected={selectedReview.rejected_vitals}
                        vitals={['hr']}
                        fallback={formatNumber(selectedReview.vitals?.pulse_bpm)}
                      />
                    </VitalCell>
                    <VitalCell
                      label={t('nurseVitalTemp')}
                      source={
                        <VitalSource
                          sources={selectedReview.vitals?.sources}
                          keys={['temperature']}
                        />
                      }
                    >
                      <RejectedVitalValue
                        rejected={selectedReview.rejected_vitals}
                        vitals={['temp']}
                        fallback={formatNumber(selectedReview.vitals?.temperature, 1)}
                      />
                    </VitalCell>
                    <VitalCell
                      label={t('nurseVitalSpo2')}
                      source={
                        <VitalSource sources={selectedReview.vitals?.sources} keys={['spo2']} />
                      }
                    >
                      <RejectedVitalValue
                        rejected={selectedReview.rejected_vitals}
                        vitals={['spo2']}
                        fallback={formatNumber(selectedReview.vitals?.spo2)}
                      />
                    </VitalCell>
                    <VitalCell
                      label={t('nurseVitalWeight')}
                      source={
                        <VitalSource sources={selectedReview.vitals?.sources} keys={['weight_kg']} />
                      }
                    >
                      <RejectedVitalValue
                        rejected={selectedReview.rejected_vitals}
                        vitals={['weight']}
                        fallback={formatNumber(selectedReview.vitals?.weight_kg)}
                      />
                    </VitalCell>
                    <VitalCell
                      label={t('nurseVitalHeight')}
                      source={
                        <VitalSource sources={selectedReview.vitals?.sources} keys={['height_cm']} />
                      }
                    >
                      <RejectedVitalValue
                        rejected={selectedReview.rejected_vitals}
                        vitals={['height']}
                        fallback={formatNumber(selectedReview.vitals?.height_cm)}
                      />
                    </VitalCell>
                    <VitalCell label="BMI">
                      <strong className="vital-value">
                        {formatBmi(
                          selectedReview.vitals?.weight_kg,
                          selectedReview.vitals?.height_cm,
                        )}
                      </strong>
                    </VitalCell>
                  </div>

                  {selectedReview.patient_follow_up ? (
                    <>
                      <h3 className="section-title">{t('nursePatientFollowUp')}</h3>
                      <p className="quoted-note">{selectedReview.patient_follow_up}</p>
                    </>
                  ) : null}

                  <h3 className="section-title">{t('nurseAssessmentSection')}</h3>
                  {canEdit ? (
                    <>
                      <p className="field-hint">{t('nurseNarrativeHint')}</p>
                      <label className="field">
                        <span className="field-label">{t('nurseChiefComplaint')}</span>
                        <textarea
                          className="field-input field-textarea"
                          rows={2}
                          value={editComplaint}
                          onChange={(e) => setEditComplaint(e.target.value)}
                        />
                      </label>
                      <label className="field">
                        <span className="field-label">{t('nurseIllnessNote')}</span>
                        <textarea
                          className="field-input field-textarea"
                          rows={3}
                          value={editNote}
                          onChange={(e) => setEditNote(e.target.value)}
                        />
                      </label>
                      <div className="field-row">
                        <label className="field">
                          <span className="field-label">{t('department')}</span>
                          <select
                            className="field-input"
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
                              .sort(
                                (a, b) =>
                                  (a.id === selectedReview.proposed_department_id ? 0 : 1) -
                                  (b.id === selectedReview.proposed_department_id ? 0 : 1),
                              )
                              .map((dept) => (
                                <option key={dept.id} value={dept.id}>
                                  {language === 'th' ? dept.name_th ?? dept.name_en : dept.name_en}
                                </option>
                              ))}
                          </select>
                        </label>
                        <label className="field">
                          <span className="field-label">{t('aiAssessmentScore')}</span>
                          <select
                            className="field-input"
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
                      </div>
                      {isReroute(selectedReview) ? (
                        <label className="field">
                          <span className="field-label">{t('adminCorrectionReason')}</span>
                          <input
                            type="text"
                            className="field-input"
                            placeholder={t('adminCorrectionReasonPlaceholder')}
                            value={editReason}
                            onChange={(e) => setEditReason(e.target.value)}
                          />
                        </label>
                      ) : null}
                    </>
                  ) : (
                    <dl className="fact-grid">
                      <div>
                        <dt>{t('nurseChiefComplaint')}</dt>
                        <dd>
                          {selectedReview.chief_complaint ??
                            selectedReview.ai_chief_complaint ??
                            '—'}
                        </dd>
                      </div>
                      <div>
                        <dt>{t('nurseIllnessNote')}</dt>
                        <dd>
                          {selectedReview.illness_note ?? selectedReview.ai_illness_note ?? '—'}
                        </dd>
                      </div>
                      <div>
                        <dt>{t('department')}</dt>
                        <dd>
                          {confirmedDeptLabel(selectedReview) ?? reviewDeptLabel(selectedReview)}
                        </dd>
                      </div>
                      {selectedReview.his_routing_status ? (
                        <div>
                          <dt>HIS</dt>
                          <dd>
                            {selectedReview.his_routing_status === 'pushed'
                              ? `${t('nurseHisPublished')}${
                                  selectedReview.his_queue_number
                                    ? ` · ${selectedReview.his_queue_number}`
                                    : ''
                                }`
                              : t('nurseHisPushFailed')}
                          </dd>
                        </div>
                      ) : null}
                      {selectedReview.ai_assessment_score ? (
                        <div>
                          <dt>{t('aiAssessmentScore')}</dt>
                          <dd>
                            {selectedReview.ai_assessment_score}/
                            {selectedReview.ai_assessment_scale}
                          </dd>
                        </div>
                      ) : null}
                      {selectedReview.reviewed_at ? (
                        <div>
                          <dt>{t('nurseFilterReviewed')}</dt>
                          <dd>
                            {selectedReview.reviewer_name
                              ? `${selectedReview.reviewer_name} · `
                              : ''}
                            {formatDateAbsolute(selectedReview.reviewed_at)}
                          </dd>
                        </div>
                      ) : null}
                    </dl>
                  )}
                </>
              ) : reviewTab === 'conversation' ? (
                sessionMessagesLoading ? (
                  <p className="muted">{t('loading')}</p>
                ) : sessionMessages.length === 0 ? (
                  <p className="muted">{t('noMessages')}</p>
                ) : (
                  <div className="transcript">
                    {sessionMessages.map((message) => (
                      <MessageBubble key={message.id} message={message} />
                    ))}
                  </div>
                )
              ) : selectedReview.patient_history ? (
                <dl className="fact-grid">
                  <div>
                    <dt>{t('hdbSmoking')}</dt>
                    <dd>{selectedReview.patient_history.smoking || '—'}</dd>
                  </div>
                  <div>
                    <dt>{t('hdbAlcohol')}</dt>
                    <dd>{selectedReview.patient_history.alcohol || '—'}</dd>
                  </div>
                  <div>
                    <dt>{t('hdbAllergies')}</dt>
                    <dd>{selectedReview.patient_history.allergies || '—'}</dd>
                  </div>
                  <div>
                    <dt>{t('hdbChronicConditions')}</dt>
                    <dd>{selectedReview.patient_history.chronic_conditions || '—'}</dd>
                  </div>
                  <div>
                    <dt>{t('hdbPostSurgeries')}</dt>
                    <dd>{selectedReview.patient_history.post_surgeries || '—'}</dd>
                  </div>
                  <div>
                    <dt>{t('hdbFamilyHistory')}</dt>
                    <dd>{selectedReview.patient_history.family_history || '—'}</dd>
                  </div>
                  <div>
                    <dt>{t('hdbHistoryRecordedAt')}</dt>
                    <dd>
                      {formatDateAbsolute(selectedReview.patient_history.recorded_at ?? null)}
                    </dd>
                  </div>
                </dl>
              ) : (
                <p className="muted">{t('nurseHistoryNone')}</p>
              )}

              {dialogError ? (
                <p className="alert-note alert-note-danger" role="alert">
                  <WarningCircle size={18} weight="fill" aria-hidden="true" />
                  {dialogError}
                </p>
              ) : null}
            </div>

            {/* Pinned, so the action the dialog exists for is never below the
                fold of a scrolling body. */}
            {step !== 'result' && canEdit && (
              <footer className="dialog-foot">
                {step === 'confirm' ? (
                  <>
                    <button type="button" className="secondary-btn" onClick={handleBackToReview}>
                      {t('back')}
                    </button>
                    <button
                      type="button"
                      className="primary-btn"
                      disabled={reviewActionLoading === selectedReview.assessment_id}
                      onClick={() => void handleConfirm(selectedReview)}
                    >
                      {t('nurseAssignSend')}
                    </button>
                  </>
                ) : (
                  <>
                    <span className="dialog-foot-note">
                      {isReroute(selectedReview)
                        ? t('nurseConfirmRerouteNote')
                        : t('nurseConfirmPublishNote')}
                    </span>
                    <button
                      type="button"
                      className="primary-btn"
                      onClick={() => void handleOpenConfirm(selectedReview)}
                    >
                      {isReroute(selectedReview)
                        ? t('nurseConfirmReroute')
                        : t('nurseConfirmPublish')}
                    </button>
                  </>
                )}
              </footer>
            )}
          </div>
        </div>
      )}
    </Layout>
  );
}
