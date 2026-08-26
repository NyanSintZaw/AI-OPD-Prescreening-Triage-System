import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { BookOpen, ChartBar, ClipboardText, WarningCircle, X } from '@phosphor-icons/react';
import { api, type MessageOut } from '../api';
import { getAdminEmail, getAdminName, getAdminRole, getAdminToken } from '../api/client';
import { Layout } from '../components/Layout';
import { MessageBubble } from '../components/MessageBubble';
import { CriteriaBook } from '../components/CriteriaBook';
import { TriageDashboard } from '../components/TriageDashboard';
import { StaffNav, type StaffNavItem } from '../components/staff/StaffNav';
import { SelectField, type SelectOption } from '../components/ui/SelectField';
import { PopoverBoundary } from '../components/ui/useFlipPlacement';
import { TriageBadge } from '../components/staff/TriageBadge';
import { useLanguage } from '../hooks/useSession';
import { useDuration } from '../hooks/useDuration';
import { DIALOG_EXIT_MS } from '../hooks/useDialogExit';
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

/** The header's actions slot — see `usePortalTarget` in the dashboard. */
export const HEAD_ACTIONS_ID = 'staff-head-actions';

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

function minutesSince(iso: string): number {
  return Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
}

/** Where a vital came from — a device reading and a patient-typed number
 *  must not look identical to the nurse. HIS-carried values show no tag. */
function VitalSource({ sources, keys }: { sources?: Record<string, string> | null; keys: string[] }) {
  const { t } = useTranslation();
  const src = keys.map((k) => sources?.[k]).find(Boolean);
  if (!src) return null;
  if (src === 'device') {
    return <span className="status-chip chip-device">{t('nurseSourceDevice')}</span>;
  }
  if (src === 'patient_input' || src === 'manual') {
    return <span className="status-chip chip-patient">{t('nurseSourcePatient')}</span>;
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
  // Label, then value, then where the value came from. The provenance tag used
  // to sit between the label and the number, so a card read as three unrelated
  // lines and the tag broke the one relationship that matters.
  return (
    <div className="vital-cell">
      <span className="vital-label">{label}</span>
      {children}
      {source}
    </div>
  );
}

type Vitals = AssessmentReviewOut['vitals'];

interface VitalRow {
  key: string;
  /** i18n key for the label. */
  label: string;
  /** Keys this cell's provenance may be stamped under. */
  sourceKeys: string[];
  /** Canonical vital keys a rejection may arrive under (BP covers sbp + dbp). */
  rejectKeys: string[];
  read: (vitals: Vitals) => string | null;
}

/** What the booth measures, in the order a nurse reads it. */
const VITAL_ROWS: VitalRow[] = [
  {
    key: 'bp',
    label: 'nurseVitalBp',
    sourceKeys: ['systolic', 'diastolic'],
    rejectKeys: ['sbp', 'dbp'],
    read: (v) => (v?.systolic && v?.diastolic ? `${v.systolic}/${v.diastolic}` : null),
  },
  {
    key: 'pulse',
    label: 'nurseVitalPulse',
    sourceKeys: ['pulse_bpm'],
    rejectKeys: ['hr'],
    read: (v) => (v?.pulse_bpm ? String(v.pulse_bpm) : null),
  },
  {
    key: 'temp',
    label: 'nurseVitalTemp',
    sourceKeys: ['temperature'],
    rejectKeys: ['temp'],
    read: (v) => (v?.temperature ? v.temperature.toFixed(1) : null),
  },
  {
    key: 'spo2',
    label: 'nurseVitalSpo2',
    sourceKeys: ['spo2'],
    rejectKeys: ['spo2'],
    read: (v) => (v?.spo2 ? String(v.spo2) : null),
  },
];

/** Body measurements. Separated from the vitals above because they answer a
 *  different question — nothing about a height reading is a clinical signal —
 *  and because seven cells in one auto-fill grid orphaned BMI onto its own row. */
const BODY_ROWS: VitalRow[] = [
  {
    key: 'weight',
    label: 'nurseVitalWeight',
    sourceKeys: ['weight_kg'],
    rejectKeys: ['weight'],
    read: (v) => (v?.weight_kg ? String(v.weight_kg) : null),
  },
  {
    key: 'height',
    label: 'nurseVitalHeight',
    sourceKeys: ['height_cm'],
    rejectKeys: ['height'],
    read: (v) => (v?.height_cm ? String(v.height_cm) : null),
  },
];

/**
 * What the booth actually captured.
 *
 * Only measured values get a cell. The grid used to render all seven
 * regardless, so four boxes holding a dash carried the same visual weight as
 * the one number that mattered — and an amber banner above them restated the
 * same absences a second time. The absences are one quiet line now, and the
 * banner is gone.
 */
function VitalsPanel({ review }: { review: AssessmentReviewOut }) {
  const { t } = useTranslation();
  const vitals = review.vitals;
  const captured = (row: VitalRow) =>
    row.read(vitals) !== null || row.rejectKeys.some((key) => review.rejected_vitals?.[key]);

  const cell = (row: VitalRow) => (
    <VitalCell
      key={row.key}
      label={t(row.label)}
      source={<VitalSource sources={vitals?.sources} keys={row.sourceKeys} />}
    >
      <RejectedVitalValue
        rejected={review.rejected_vitals}
        vitals={row.rejectKeys}
        fallback={row.read(vitals) ?? '—'}
      />
    </VitalCell>
  );

  const measured = VITAL_ROWS.filter(captured);
  const body = BODY_ROWS.filter(captured);
  const bmi = formatBmi(vitals?.weight_kg, vitals?.height_cm);
  // The engine's own list is authoritative — it names what the criteria wanted
  // and never got, including vitals that have no cell here at all (rr).
  const missing = review.missing_vitals?.length
    ? review.missing_vitals.map((key) => t(`nurseMissingVitalName_${key}`, { defaultValue: key }))
    : VITAL_ROWS.filter((row) => !captured(row)).map((row) => t(row.label));

  // Three groups, each with its own heading. One card treatment across all of
  // them — when the groups were told apart by *styling* instead, the measured
  // vitals and the body measurements read as two unrelated kinds of thing.
  return (
    <>
      {measured.length > 0 && (
        <section className="review-block">
          <h3 className="section-title">{t('nurseMeasuredAtBooth')}</h3>
          <div className="vitals-grid">{measured.map(cell)}</div>
        </section>
      )}

      {missing.length > 0 && (
        <section className="review-block">
          <h3 className="section-title">{t('nurseMissingVitals')}</h3>
          <ul className="vitals-missing">
            {missing.map((name) => (
              <li key={name}>{name}</li>
            ))}
          </ul>
        </section>
      )}

      {(body.length > 0 || bmi !== '—') && (
        <section className="review-block">
          <h3 className="section-title">{t('nurseBodySection')}</h3>
          <div className="vitals-grid">
            {body.map(cell)}
            {bmi !== '—' && (
              <VitalCell label="BMI">
                <strong className="vital-value">{bmi}</strong>
              </VitalCell>
            )}
          </div>
        </section>
      )}
    </>
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
        <WarningCircle size={18} weight="duotone" aria-hidden="true" />
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
  const formatDuration = useDuration();
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
  const [levelFilter, setLevelFilter] = useState<string>('all');
  const [reviews, setReviews] = useState<AssessmentReviewOut[]>([]);
  const [departments, setDepartments] = useState<DepartmentOut[]>([]);
  const [authError, setAuthError] = useState<string | null>(null);
  const [reviewActionLoading, setReviewActionLoading] = useState<string | null>(null);
  const [slipQuery, setSlipQuery] = useState('');
  const [reviewDataLoading, setReviewDataLoading] = useState(true);
  // Recomputes the "waiting" column without refetching.
  const [, setClockTick] = useState(0);

  const [selectedReview, setSelectedReview] = useState<AssessmentReviewOut | null>(null);
  // The card's exit: see `dismissReview`.
  const [leavingDialog, setLeavingDialog] = useState(false);
  const closeTimer = useRef(0);
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
  const dialogCardRef = useRef<HTMLDivElement>(null);

  const staffEmail = getAdminEmail() ?? t('loginNurseTab');
  const staffName = getAdminName();
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

  useEffect(() => () => window.clearTimeout(closeTimer.current), []);

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

  /**
   * Close the case, after the card has left.
   *
   * The dialog is mounted from `selectedReview`, so clearing it is what
   * unmounts the card — and doing that on the click makes it vanish rather
   * than leave. This flags it leaving, lets `--dur-exit` run, and tears down
   * once nothing is on screen.
   *
   * `after` exists for the same reason: the assign result drives what the
   * final step shows, so clearing it on the click would blank the card while
   * it was still fading.
   */
  const dismissReview = (after?: () => void) => {
    if (closeTimer.current) return; // a second Escape during the exit
    setLeavingDialog(true);
    closeTimer.current = window.setTimeout(() => {
      closeTimer.current = 0;
      setLeavingDialog(false);
      setSelectedReview(null);
      setSessionMessages([]);
      setStep('review');
      after?.();
    }, DIALOG_EXIT_MS);
  };

  const handleCloseReview = () => dismissReview();

  const handleFinishAssign = () => dismissReview(() => setAssignResult(null));

  /** Human name for a department id, from the list already loaded. */
  const departmentLabel = (departmentId?: string | null) => {
    const dept = departments.find((d) => d.id === departmentId);
    if (!dept) return '—';
    return language === 'th' ? dept.name_th ?? dept.name_en : dept.name_en;
  };

  const deptFilterOptions: SelectOption[] = [
    { value: 'all', label: t('nurseDeptFilterAll') },
    ...departments.map((dept) => ({
      value: dept.id,
      label: (language === 'th' ? dept.name_th ?? dept.name_en : dept.name_en) ?? dept.id,
    })),
  ];

  /* Number and name are one label, not a label and a hint. Split across the
     two, the name rendered at hint size — so the level list read a step
     smaller than the department list beside it, for no reason a nurse could
     see. `hint` is for genuinely secondary text; a level's name is not that. */
  const levelFilterOptions: SelectOption[] = [
    { value: 'all', label: t('nurseLevelFilterAll') },
    ...[1, 2, 3, 4, 5].map((level) => ({
      value: String(level),
      label: t(`triageLevelName_${level}`),
      /* The same badge the queue rows carry, not a new icon. DESIGN.md scopes
         triage colour to these surfaces and calls it the one colour that
         carries meaning here — a level filter is exactly that meaning — and
         reusing the badge means the filter shows the object it filters for
         rather than a second encoding of it. The digit lives in the badge, so
         the label is just the name. */
      icon: <TriageBadge level={level} />,
    })),
  ];

  const scoreOptions: SelectOption[] = Array.from({ length: 10 }, (_, index) => ({
    value: String(index + 1),
    label: `${index + 1}/10`,
  }));

  /** OPD departments a nurse may reroute to, with the engine's own proposal
   *  first — it is also the pre-selected value, so the list opens on it. */
  const routableDepartments = (review: AssessmentReviewOut): SelectOption[] =>
    departments
      .filter((dept) => dept.kind === 'opd' || dept.id === review.proposed_department_id)
      .sort(
        (a, b) =>
          (a.id === review.proposed_department_id ? 0 : 1) -
          (b.id === review.proposed_department_id ? 0 : 1),
      )
      .map((dept) => ({
        value: dept.id,
        label: (language === 'th' ? dept.name_th ?? dept.name_en : dept.name_en) ?? dept.id,
      }));

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
        // A row the engine never disposed carries no level, so it matches no
        // specific level — only "all".
        if (levelFilter !== 'all' && String(review.triage_level ?? '') !== levelFilter) {
          return false;
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
  }, [reviews, slipQuery, deptFilter, levelFilter]);

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
      staffEmail={staffEmail}
      sidebar={
        <StaffNav
          items={navItems}
          active={activeSection}
          onSelect={setActiveSection}
          title={t('nursePortalTitle')}
          accountName={staffName}
          accountEmail={staffEmail}
          onLogout={handleLogout}
        />
      }
    >
      <section
        className={`staff-page ${activeSection === 'dashboard' ? '' : 'staff-page-fill'}`}
      >
        <header className="staff-page-head">
          <div>
            <h1>{sectionTitle[activeSection]}</h1>
            <p className="muted">{sectionSubtitle[activeSection]}</p>
          </div>
          {/* Where a section's own controls land. The dashboard's period
              toolbar portals in here rather than opening a row of its own
              below, which was right-aligned over an empty two-thirds. */}
          <div id={HEAD_ACTIONS_ID} className="staff-head-actions" />
        </header>

        {authError ? (
          <p className="alert-note alert-note-danger" role="alert">
            <WarningCircle size={18} weight="duotone" aria-hidden="true" />
            {authError}
          </p>
        ) : null}

        {activeSection === 'criteria' && <CriteriaBook />}
        {activeSection === 'dashboard' && (
          <TriageDashboard onOpenQueue={() => setActiveSection('queue')} />
        )}

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
              <SelectField
                className="staff-toolbar-select"
                value={deptFilter}
                onChange={setDeptFilter}
                options={deptFilterOptions}
                aria-label={t('nurseDeptFilterLabel')}
                emptyText={t('nurseNoMatches')}
              />
              {/* Acuity is what the queue is sorted by, so it is also what a
                  nurse most often wants to narrow to — "show me the 2s". */}
              <SelectField
                className="staff-toolbar-select"
                value={levelFilter}
                onChange={setLevelFilter}
                options={levelFilterOptions}
                aria-label={t('nurseLevelFilterLabel')}
                emptyText={t('nurseNoMatches')}
              />
              <div className="staff-toolbar-end">
                <span className="queue-count" aria-live="polite">
                  {t('nurseQueueCount', { n: filteredReviews.length })}
                </span>
                <button
                  type="button"
                  className="secondary-btn"
                  onClick={() => void loadReviewData(reviewFilter)}
                  disabled={reviewDataLoading}
                >
                  {t('adminRefresh')}
                </button>
              </div>
            </div>

            {/* One surface that owns the remaining height, whatever it holds —
                loading, empty, or rows. Three rows used to sit at the top of
                700px of blank paper. */}
            <div className="queue-surface">
              {reviewDataLoading && reviews.length === 0 ? (
                <div className="staff-empty">
                  <p>{t('loading')}</p>
                </div>
              ) : filteredReviews.length === 0 ? (
                <div className="staff-empty">
                  <p>{t('adminNoReviews')}</p>
                </div>
              ) : (
              <div className="table-wrap scroll-slim">
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
                      <th scope="col" className="col-status">
                        {t('status')}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredReviews.map((review) => {
                      const confirmed = confirmedDeptLabel(review);
                      const waited = minutesSince(review.created_at);
                      const deptText =
                        review.status === 'corrected' && confirmed
                          ? confirmed
                          : reviewDeptLabel(review);
                      return (
                        <tr
                          key={review.id}
                          className={`queue-row ${review.triage_level && review.triage_level <= 2 ? 'row-urgent' : ''} ${review.status === 'pending' ? '' : 'is-done'}`}
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
                            <code className="code-chip">{slipCode(review.session_id)}</code>
                          </td>
                          <td className="queue-name" title={review.patient_name ?? undefined}>
                            {review.patient_name || '—'}
                          </td>
                          <td className="col-complaint">{complaintPreview(review)}</td>
                          <td title={deptText}>{deptText}</td>
                          <td className="col-num queue-wait">
                            {review.status === 'pending' ? formatDuration(waited) : '—'}
                          </td>
                          <td className="col-status">
                            <span className={`status-chip chip-${review.status}`}>
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
            </div>
          </>
        )}
      </section>

      {selectedReview && (
        /* The card, not the window, is where a popup has to flip: the
           department picker sits low in the decision column, and measured
           against the viewport it has room below it that the dialog does not. */
        <PopoverBoundary value={dialogCardRef}>
          <div
            className="dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="nurse-review-dialog-title"
          >
          <button
            type="button"
            className="dialog-backdrop"
            data-leaving={leavingDialog || undefined}
            aria-label={t('close')}
            onClick={handleCloseReview}
          />
          <div
            className="dialog-card"
            ref={dialogCardRef}
            data-leaving={leavingDialog || undefined}
          >
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
                    <code className="code-chip">{slipCode(selectedReview.session_id)}</code>
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
              <div className="tabs" role="tablist">
                {(['assessment', 'conversation', 'history'] as const).map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    role="tab"
                    aria-selected={reviewTab === tab}
                    className={`tab ${reviewTab === tab ? 'active' : ''}`}
                    onClick={() => setReviewTab(tab)}
                  >
                    {tab === 'assessment'
                      ? t('nurseAssessmentTab')
                      : tab === 'conversation'
                        ? t('nurseConversationTitle')
                        : t('nurseHistoryTab')}
                    {tab === 'conversation' ? (
                      <span className="tab-count">
                        {sessionMessagesLoading ? '…' : sessionMessages.length}
                      </span>
                    ) : null}
                  </button>
                ))}
              </div>
            )}

            {/* Keyed so the body is a new element on every swap — that is what
                lets its `@starting-style` fade run. The step is in the key as
                well as the tab: review → confirm → result is the larger change
                of the two and wants the same settle. */}
            <div className="dialog-body" key={`${step}-${reviewTab}`}>
              {step === 'result' && assignResult ? (
                <AssignResult review={assignResult} onDone={handleFinishAssign} />
              ) : step === 'confirm' ? (
                <>
                  <p className="alert-note alert-note-warning">
                    <WarningCircle size={18} weight="duotone" aria-hidden="true" />
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
                /* Evidence on the left, the decision on the right. One
                   2000px-tall scroll asked the nurse to hold the reasoning in
                   their head while they scrolled past it to the department
                   they were being asked to agree with. */
                <div className="review-split">
                  <div className="review-evidence">
                    {/* The record keys, whole. The header truncates the VN to 12
                        characters because an 18-digit number beside a patient's
                        name is the widest thing in the row — here there is room
                        to print it, and this is where a nurse copying into the
                        HIS goes looking for it. */}
                    <section className="review-keys">
                      <div className="review-keys-item">
                        <span className="review-keys-label">{t('nurseHnLabel')}</span>
                        <code className="review-keys-value">
                          {selectedReview.patient_hn || '—'}
                        </code>
                      </div>
                      <div className="review-keys-item">
                        <span className="review-keys-label">VN</span>
                        <code className="review-keys-value">
                          {selectedReview.visit_id || '—'}
                        </code>
                      </div>
                    </section>

                    {Object.keys(selectedReview.rejected_vitals ?? {}).length > 0 && (
                      <p className="alert-note alert-note-danger" role="alert">
                        <WarningCircle size={18} weight="duotone" aria-hidden="true" />
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

                    <VitalsPanel review={selectedReview} />

                    {selectedReview.patient_follow_up ? (
                      <>
                        <h3 className="section-title">{t('nursePatientFollowUp')}</h3>
                        <p className="quoted-note">{selectedReview.patient_follow_up}</p>
                      </>
                    ) : null}

                    {/* The engine's own fired rules — the authoritative clinical
                        signal behind this level. Open by default: it was a
                        collapsed <details>, which hid the reasoning the nurse is
                        being asked to agree with. Pinned to the foot of the
                        column, because it is what the measurements above add
                        up to. */}
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
                  </div>

                  <div className="review-decision">
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
                        {/* The one field that takes the column's leftover
                            height. A note a nurse may add to deserves the room
                            more than the empty space below the form did. */}
                        <label className="field field-grow">
                          <span className="field-label">{t('nurseIllnessNote')}</span>
                          <textarea
                            className="field-input field-textarea"
                            rows={3}
                            value={editNote}
                            onChange={(e) => setEditNote(e.target.value)}
                          />
                        </label>
                        <div className="field-row">
                          <SelectField
                            label={t('department')}
                            value={editDeptId}
                            onChange={setEditDeptId}
                            options={routableDepartments(selectedReview)}
                            placeholder={t('adminSelectDepartment')}
                            emptyText={t('nurseNoMatches')}
                          />
                          <SelectField
                            label={t('aiAssessmentScore')}
                            value={editScore}
                            onChange={setEditScore}
                            options={scoreOptions}
                            placeholder={t('aiAssessmentScorePlaceholder')}
                            emptyText={t('nurseNoMatches')}
                          />
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
                  </div>
                </div>
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
                /* Seven fields in one auto-fit grid ranked a timestamp level
                   with an anaphylaxis allergy and left an orphan row. Grouped
                   by what a nurse needs and in what order: what could hurt the
                   patient, then their medical background, then lifestyle, with
                   the capture date demoted to a footer — it is metadata about
                   the record, not a fact about the person. */
                <div className="review-history">
                  <section className="review-block">
                    <h3 className="section-title">{t('hdbAllergies')}</h3>
                    <p className="history-lead">
                      {selectedReview.patient_history.allergies || '—'}
                    </p>
                  </section>

                  <section className="review-block">
                    <h3 className="section-title">{t('nurseHistoryBackground')}</h3>
                    <dl className="fact-grid">
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
                    </dl>
                  </section>

                  <section className="review-block">
                    <h3 className="section-title">{t('nurseHistoryLifestyle')}</h3>
                    <dl className="fact-grid">
                      <div>
                        <dt>{t('hdbSmoking')}</dt>
                        <dd>{selectedReview.patient_history.smoking || '—'}</dd>
                      </div>
                      <div>
                        <dt>{t('hdbAlcohol')}</dt>
                        <dd>{selectedReview.patient_history.alcohol || '—'}</dd>
                      </div>
                    </dl>
                  </section>

                  <p className="history-recorded">
                    {t('hdbHistoryRecordedAt')}:{' '}
                    {formatDateAbsolute(selectedReview.patient_history.recorded_at ?? null)}
                  </p>
                </div>
              ) : (
                <p className="muted">{t('nurseHistoryNone')}</p>
              )}

              {dialogError ? (
                <p className="alert-note alert-note-danger" role="alert">
                  <WarningCircle size={18} weight="duotone" aria-hidden="true" />
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
        </PopoverBoundary>
      )}
    </Layout>
  );
}
