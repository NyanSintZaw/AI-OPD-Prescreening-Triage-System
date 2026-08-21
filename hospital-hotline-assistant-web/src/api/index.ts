import { baseUrl, request, setAdminSession } from './client';
import type {
  AdminLoginRequest,
  AdminLoginResponse,
  ApiError,
  AssessmentReviewApproveRequest,
  AssessmentReviewCorrectRequest,
  AssessmentReviewOut,
  BpRestStatusOut,
  BloodPressureFetchResponse,
  BpDeviceStatusOut,
  BpPairRequest,
  BpPairResponse,
  BpScanResponse,
  TempDeviceStatusOut,
  TempPairRequest,
  TempPairResponse,
  TempScanResponse,
  TemperatureFetchResponse,
  Spo2DeviceStatusOut,
  Spo2FetchResponse,
  Spo2PairRequest,
  Spo2PairResponse,
  Spo2ScanResponse,
  ConversationSummaryOut,
  CriteriaActiveView,
  DepartmentOut,
  DepartmentRecommendationCreate,
  DoctorCreate,
  DoctorOut,
  DoctorScheduleCreate,
  DoctorScheduleOut,
  DoctorUpdate,
  DoctorWithSchedulesOut,
  EmergencyEventOut,
  EmergencyEventCreate,
  EmergencyTriggerOut,
  FollowUpQuestionOut,
  LanguageCode,
  MessageCreate,
  MessageOut,
  HisConnection,
  HisConnectionUpdate,
  HisVisitSummary,
  HisVisitDetail,
  HisVisitsResponse,
  HisVisitDetailResponse,
  HisPatientsResponse,
  AdminManagedUser,
  AdminUserCreateRequest,
  AdminUserUpdateRequest,
  LinkVisitRequest,
  LinkVisitResponse,
  ConfirmVisitNameRequest,
  ConfirmVisitNameResponse,
  PatientHistoryIntakeRequest,
  PatientHistoryIntakeResponse,
  KioskStats,
  RoutingRuleOut,
  RoutingFeedbackOut,
  SbarFields,
  SbarPreviewRequest,
  SessionByVisitOut,
  SessionCreate,
  SessionOut,
  SessionUpdate,
  SessionVitalsUpdate,
  SeverityAssessmentCreate,
  SttResponsePayload,
  SurveillanceSummaryOut,
  SymptomEntryCreate,
  TriageManualUploadOut,
  AiMetricsOut,
  CriteriaDiffOut,
  CriteriaEditResponse,
  CriteriaVersionDetail,
  CriteriaVersionSummary,
  VitalBoundsOut,
} from './types';

async function detailFromResponse(response: Response): Promise<string> {
  let detail = response.statusText;
  try {
    const body = (await response.json()) as ApiError;
    detail = body.detail ?? detail;
  } catch {
    // ignore
  }
  return detail;
}

async function ttsRequest(payload: { text: string; language: LanguageCode }): Promise<Blob> {
  const response = await fetch(`${baseUrl}/tts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await detailFromResponse(response));
  }
  return response.blob();
}

async function sttRequest(payload: {
  audio: Blob;
  language: LanguageCode;
  filename?: string;
}): Promise<SttResponsePayload> {
  const form = new FormData();
  form.append('audio', payload.audio, payload.filename ?? 'speech.webm');
  form.append('language', payload.language);

  const response = await fetch(`${baseUrl}/stt`, {
    method: 'POST',
    body: form,
  });
  if (!response.ok) {
    throw new Error(await detailFromResponse(response));
  }
  return response.json() as Promise<SttResponsePayload>;
}

export const api = {
  health: () => request<{ status: string; environment: string }>('/health'),

  adminLogin: async (payload: AdminLoginRequest) => {
    const response = await request<AdminLoginResponse>('/admin/login', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    setAdminSession(response.access_token, {
      email: response.user.email,
      role: response.user.role,
    });
    return response;
  },

  adminLogout: () => {
    // Revoke server-side first (best-effort — the token header is injected
    // by `request`), then drop the local session either way.
    void request<void>('/admin/logout', { method: 'POST' }).catch(() => {});
    setAdminSession(null);
  },

  /** Public kiosk home-screen counters (visitors / navigated / sessions today). */
  getKioskStats: () => request<KioskStats>('/kiosk/stats'),

  createSession: (payload: SessionCreate) =>
    request<SessionOut>('/sessions', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getSession: (sessionId: string) => request<SessionOut>(`/sessions/${sessionId}`),

  /** Most recent active session linked to this hospital visit (VN), if any. */
  getSessionByVisit: (visitId: string) =>
    request<SessionByVisitOut>(`/sessions/by-visit/${encodeURIComponent(visitId)}`),

  linkVisit: (sessionId: string, visitId: string, preconfirmed = false) =>
    request<LinkVisitResponse>(`/sessions/${sessionId}/link-visit`, {
      method: 'POST',
      body: JSON.stringify({ visit_id: visitId, preconfirmed } satisfies LinkVisitRequest),
    }),

  unlinkVisit: (sessionId: string) =>
    request<SessionOut>(`/sessions/${sessionId}/link-visit`, {
      method: 'DELETE',
    }),

  confirmVisitName: (sessionId: string, payload: ConfirmVisitNameRequest) =>
    request<ConfirmVisitNameResponse>(`/sessions/${sessionId}/confirm-visit-name`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  savePatientHistory: (sessionId: string, payload: PatientHistoryIntakeRequest) =>
    request<PatientHistoryIntakeResponse>(`/sessions/${sessionId}/patient-history`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  updateSession: (sessionId: string, payload: SessionUpdate) =>
    request<SessionOut>(`/sessions/${sessionId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  createMessage: (sessionId: string, payload: MessageCreate) =>
    request<MessageOut>(`/sessions/${sessionId}/messages`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  listMessages: (sessionId: string) =>
    request<MessageOut[]>(`/sessions/${sessionId}/messages`),

  createSymptomEntry: (sessionId: string, payload: SymptomEntryCreate) =>
    request<Record<string, unknown>>(`/sessions/${sessionId}/symptoms`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  createSeverityAssessment: (sessionId: string, payload: SeverityAssessmentCreate) =>
    request<Record<string, unknown>>(`/sessions/${sessionId}/severity-assessments`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  createDepartmentRecommendation: (
    sessionId: string,
    payload: DepartmentRecommendationCreate,
  ) =>
    request<Record<string, unknown>>(`/sessions/${sessionId}/department-recommendations`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  createEmergencyEvent: (sessionId: string, payload: EmergencyEventCreate) =>
    request<Record<string, unknown>>(`/sessions/${sessionId}/emergency-events`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  listEmergencyEvents: (sessionId: string) =>
    request<EmergencyEventOut[]>(`/sessions/${sessionId}/emergency-events`),

  createFollowUpQuestion: (
    sessionId: string,
    payload: { question_text: string; reason?: string | null },
  ) =>
    request<FollowUpQuestionOut>(`/sessions/${sessionId}/follow-up-questions`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  listFollowUpQuestions: (sessionId: string) =>
    request<FollowUpQuestionOut[]>(`/sessions/${sessionId}/follow-up-questions`),

  answerFollowUpQuestion: (sessionId: string, questionId: string, answerMessageId: string) =>
    request<FollowUpQuestionOut>(
      `/sessions/${sessionId}/follow-up-questions/${questionId}/answer`,
      {
        method: 'PATCH',
        body: JSON.stringify({ answer_message_id: answerMessageId }),
      },
    ),

  listDepartments: () => request<DepartmentOut[]>('/departments'),

  listRoutingRules: () => request<RoutingRuleOut[]>('/routing-rules'),

  listEmergencyTriggers: () => request<EmergencyTriggerOut[]>('/emergency-triggers'),

  getConversationSummary: () =>
    request<ConversationSummaryOut[]>('/conversation-summary'),

  listAssessmentReviews: (
    status: 'all' | 'pending' | 'reviewed' | 'approved' | 'corrected' = 'pending',
  ) => request<AssessmentReviewOut[]>(`/admin/reviews?status=${status}`),

  getPendingReviewCount: () =>
    request<{ pending: number }>('/admin/reviews/pending-count'),

  approveAssessmentReview: (
    assessmentId: string,
    payload: AssessmentReviewApproveRequest = {},
  ) =>
    request<AssessmentReviewOut>(`/admin/reviews/${assessmentId}/approve`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  correctAssessmentReview: (
    assessmentId: string,
    payload: AssessmentReviewCorrectRequest,
  ) =>
    request<AssessmentReviewOut>(`/admin/reviews/${assessmentId}/correct`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** Build the SBAR the nurse is about to send, from their current draft, so
   *  it can be reviewed and edited before it fires. */
  previewReviewSbar: (assessmentId: string, draft: SbarPreviewRequest) =>
    request<SbarFields>(`/admin/reviews/${assessmentId}/sbar-preview`, {
      method: 'POST',
      body: JSON.stringify(draft),
    }),

  listRoutingFeedback: () => request<RoutingFeedbackOut[]>('/admin/feedback'),

  tts: (text: string, language: LanguageCode) => ttsRequest({ text, language }),

  stt: (audio: Blob, language: LanguageCode, filename?: string) =>
    sttRequest({ audio, language, filename }),

  // ── Doctor schedules ──────────────────────────────────────────────────────
  listDoctors: (activeOnly = true) =>
    request<DoctorOut[]>(`/doctors?active_only=${activeOnly}`),

  createDoctor: (payload: DoctorCreate) =>
    request<DoctorOut>('/doctors', { method: 'POST', body: JSON.stringify(payload) }),

  updateDoctor: (doctorId: string, payload: DoctorUpdate) =>
    request<DoctorOut>(`/doctors/${doctorId}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  getDoctor: (doctorId: string) =>
    request<DoctorWithSchedulesOut>(`/doctors/${doctorId}`),

  listDoctorSchedules: (doctorId: string, fromDate?: string) =>
    request<DoctorScheduleOut[]>(`/doctors/${doctorId}/schedules${fromDate ? `?from_date=${fromDate}` : ''}`),

  addDoctorSchedule: (doctorId: string, payload: DoctorScheduleCreate) =>
    request<DoctorScheduleOut>(`/doctors/${doctorId}/schedules`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  updateDoctorSchedule: (doctorId: string, scheduleId: string, payload: DoctorScheduleCreate) =>
    request<DoctorScheduleOut>(`/doctors/${doctorId}/schedules/${scheduleId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  deleteDoctorSchedule: (doctorId: string, scheduleId: string) =>
    request<void>(`/doctors/${doctorId}/schedules/${scheduleId}`, { method: 'DELETE' }),

  getAvailableDoctors: (scheduleDate?: string) =>
    request<DoctorWithSchedulesOut[]>(
      `/schedules/available${scheduleDate ? `?schedule_date=${scheduleDate}` : ''}`,
    ),

  // ── Vitals (blood pressure kiosk) ──────────────────────────────────────────
  fetchBloodPressure: (sessionId?: string | null) =>
    request<BloodPressureFetchResponse>('/vitals/blood-pressure/fetch', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId ?? null }),
    }),

  /** Long-poll: resolves as soon as the cuff broadcasts a finished
   *  measurement and the backend has pulled it, or with status
   *  'not_seen' after timeoutSeconds so the caller can re-arm. */
  watchBloodPressure: (sessionId?: string | null, timeoutSeconds = 25) =>
    request<BloodPressureFetchResponse>('/vitals/blood-pressure/watch', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId ?? null, timeout_seconds: timeoutSeconds }),
    }),

  /** Physiologically possible ranges from the active criteria version, so the
   *  kiosk shows the nurse-approved wording instead of a bare 422. */
  getVitalBounds: () => request<VitalBoundsOut>('/screening/vital-bounds'),

  getBpRestStatus: (sessionId?: string | null) => {
    const q = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
    return request<BpRestStatusOut>(`/vitals/blood-pressure/rest-status${q}`);
  },

  updateSessionVitals: (sessionId: string, payload: SessionVitalsUpdate) =>
    request<{
      session_id: string;
      vitals: Record<string, unknown>;
      /** Present when this (first) crisis reading opened a 15-minute rest
       *  window: the patient rests and re-measures before the assessment
       *  continues — the reading itself is provisional. */
      bp_recheck?: { required: boolean; rest_until: string; seconds_remaining: number };
      bp_rest_until?: string;
    }>(
      `/sessions/${sessionId}/vitals`,
      { method: 'PUT', body: JSON.stringify(payload) },
    ),

  /** Record a single vital the engine requested mid-interview (e.g. the
   *  temperature-on-demand popup, or weight/height near the end of the
   *  interview). Merges into the session's stored vitals. */
  updateSessionMeasurement: (
    sessionId: string,
    payload: { vital: 'temp' | 'weight' | 'height' | 'spo2'; value: number },
  ) =>
    request<{ session_id: string; vitals: Record<string, unknown> }>(
      `/sessions/${sessionId}/measurement`,
      { method: 'POST', body: JSON.stringify(payload) },
    ),

  /** Long-poll the kiosk thermometer: resolves when the device pushes a
   *  measurement (the beep), or with status 'timeout' after timeoutSeconds. */
  fetchTemperature: (sessionId?: string | null, timeoutSeconds = 60) =>
    request<TemperatureFetchResponse>('/vitals/temperature/fetch', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId ?? null, timeout_seconds: timeoutSeconds }),
    }),

  getBpDeviceStatus: () => request<BpDeviceStatusOut>('/admin/bp-device'),

  scanBpDevices: () =>
    request<BpScanResponse>('/admin/bp-device/scan', { method: 'POST' }),

  pairBpDevice: (payload: BpPairRequest) =>
    request<BpPairResponse>('/admin/bp-device/pair', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getTempDeviceStatus: () => request<TempDeviceStatusOut>('/admin/temp-device'),

  scanTempDevices: () =>
    request<TempScanResponse>('/admin/temp-device/scan', { method: 'POST' }),

  pairTempDevice: (payload: TempPairRequest) =>
    request<TempPairResponse>('/admin/temp-device/pair', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** Take one stable SpO2/pulse reading from the fingertip oximeter:
   *  resolves once the values hold steady for the stability window (the
   *  device needs ~30-60 s to settle after finger insertion), or with
   *  status 'timeout' (no finger) / 'unstable' (never steadied). */
  fetchSpo2: (sessionId?: string | null, timeoutSeconds = 75) =>
    request<Spo2FetchResponse>('/vitals/spo2/fetch', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId ?? null, timeout_seconds: timeoutSeconds }),
    }),

  getSpo2DeviceStatus: () => request<Spo2DeviceStatusOut>('/admin/spo2-device'),

  scanSpo2Devices: () =>
    request<Spo2ScanResponse>('/admin/spo2-device/scan', { method: 'POST' }),

  pairSpo2Device: (payload: Spo2PairRequest) =>
    request<Spo2PairResponse>('/admin/spo2-device/pair', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // ── Disease Surveillance ───────────────────────────────────────────────────
  getSurveillanceSummary: (days = 7) =>
    request<SurveillanceSummaryOut>(`/admin/surveillance?days=${days}`),

  // ── Hospital DB (mock HIS) read-only view ──────────────────────────────────
  getHisVisits: () => request<HisVisitsResponse>('/admin/his/visits'),

  getHisVisit: (visitId: string) =>
    request<HisVisitDetailResponse>(`/admin/his/visits/${visitId}`),

  getHisPatients: () => request<HisPatientsResponse>('/admin/his/patients'),

  getHisConnection: () => request<HisConnection>('/admin/his/connection'),

  updateHisConnection: (payload: HisConnectionUpdate) =>
    request<HisConnection>('/admin/his/connection', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),

  disconnectHisConnection: () =>
    request<HisConnection>('/admin/his/connection', { method: 'DELETE' }),

  // ── Nurse account management (admin → User Settings) ─────────────────────
  listAdminUsers: () => request<AdminManagedUser[]>('/admin/users'),

  createAdminUser: (payload: AdminUserCreateRequest) =>
    request<AdminManagedUser>('/admin/users', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  updateAdminUser: (userId: string, payload: AdminUserUpdateRequest) =>
    request<AdminManagedUser>(`/admin/users/${userId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  deleteAdminUser: (userId: string) =>
    request<void>(`/admin/users/${userId}`, { method: 'DELETE' }),

  // ── Triage manual PDF upload ───────────────────────────────────────────────
  uploadTriageManual: async (file: File): Promise<TriageManualUploadOut> => {
    const token = (await import('./client')).getAdminToken();
    const form = new FormData();
    form.append('file', file);
    const response = await fetch(`${baseUrl}/admin/triage-manual/upload`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    });
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const body = (await response.json()) as { detail?: string };
        detail = body.detail ?? detail;
      } catch { /* ignore */ }
      throw new Error(detail);
    }
    return response.json() as Promise<TriageManualUploadOut>;
  },

  getTriageManualStatus: () =>
    request<TriageManualUploadOut | null>('/admin/triage-manual/status'),

  /** Read-only, nurse-shaped view of the criteria the booth decides with. */
  getActiveCriteria: () => request<CriteriaActiveView>('/admin/criteria/active'),

  // ── Screening criteria governance (engine v2) ─────────────────────────────
  listCriteriaVersions: () =>
    request<CriteriaVersionSummary[]>('/admin/criteria/versions'),

  getCriteriaVersion: (versionId: string) =>
    request<CriteriaVersionDetail>(`/admin/criteria/versions/${versionId}`),

  getCriteriaDiff: (versionId: string, against?: string) =>
    request<CriteriaDiffOut>(
      `/admin/criteria/versions/${versionId}/diff${against ? `?against=${against}` : ''}`,
    ),

  updateCriteriaVersion: (versionId: string, criteria: Record<string, unknown>) =>
    request<CriteriaEditResponse>(`/admin/criteria/versions/${versionId}`, {
      method: 'PUT',
      body: JSON.stringify(criteria),
    }),

  submitCriteriaVersion: (versionId: string) =>
    request<{ id: string; status: string }>(
      `/admin/criteria/versions/${versionId}/submit`,
      { method: 'POST' },
    ),

  approveCriteriaVersion: (versionId: string) =>
    request<{ id: string; status: string }>(
      `/admin/criteria/versions/${versionId}/approve`,
      { method: 'POST' },
    ),

  activateCriteriaVersion: (versionId: string) =>
    request<{ id: string; status: string }>(
      `/admin/criteria/versions/${versionId}/activate`,
      { method: 'POST' },
    ),

  getAiMetrics: (params: { from?: string; to?: string } = {}) => {
    const query = new URLSearchParams();
    if (params.from) query.set('from', params.from);
    if (params.to) query.set('to', params.to);
    const suffix = query.toString();
    return request<AiMetricsOut>(`/admin/ai-metrics${suffix ? `?${suffix}` : ''}`);
  },
};

export type { CriteriaActiveView, MessageOut, SessionOut, ConversationSummaryOut, DepartmentOut, DoctorOut, DoctorWithSchedulesOut, DoctorScheduleOut, SurveillanceSummaryOut, TriageManualUploadOut, AiMetricsOut, CriteriaDiffOut, CriteriaVersionDetail, CriteriaVersionSummary, LinkVisitResponse, HisVisitSummary, HisVisitDetail, KioskStats };
