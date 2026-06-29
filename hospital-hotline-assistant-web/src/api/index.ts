import { baseUrl, request, setAdminSession } from './client';
import type {
  AdminLoginRequest,
  AdminLoginResponse,
  ApiError,
  AssessmentReviewApproveRequest,
  AssessmentReviewCorrectRequest,
  AssessmentReviewOut,
  ChatRequestPayload,
  ChatResponsePayload,
  ChatStreamEvent,
  ConversationSummaryOut,
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
  RoutingRuleOut,
  RoutingFeedbackOut,
  SessionCreate,
  SessionLocationUpdate,
  SessionOut,
  SessionUpdate,
  SeverityAssessmentCreate,
  SttResponsePayload,
  SurveillanceSummaryOut,
  SymptomEntryCreate,
  TriageManualUploadOut,
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
    setAdminSession(null);
  },

  createSession: (payload: SessionCreate) =>
    request<SessionOut>('/sessions', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getSession: (sessionId: string) => request<SessionOut>(`/sessions/${sessionId}`),

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

  chat: (sessionId: string, payload: ChatRequestPayload) =>
    request<ChatResponsePayload>(`/sessions/${sessionId}/chat`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /**
   * Open a streaming chat turn. Yields parsed event objects as the
   * server emits them (Server-Sent Events / NDJSON-in-SSE framing).
   *
   * Event shapes mirror the backend's
   * ``triage_service.process_chat_stream`` (see that docstring for the
   * authoritative list). Use the ``signal`` to cancel mid-stream when
   * the user navigates away or starts a new turn.
   */
  async *chatStream(
    sessionId: string,
    payload: ChatRequestPayload,
    signal?: AbortSignal,
  ): AsyncGenerator<ChatStreamEvent, void, void> {
    const response = await fetch(`${baseUrl}/sessions/${sessionId}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(payload),
      signal,
    });
    if (!response.ok || !response.body) {
      throw new Error(await detailFromResponse(response));
    }

    // SSE parsing: frames are separated by ``\n\n``. Each frame has a
    // ``data: <json>`` line we care about. We buffer partial frames
    // across read() boundaries because TCP doesn't honour our nice
    // logical message boundaries — a single chunk may end mid-JSON,
    // or carry multiple events.
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let separator = buffer.indexOf('\n\n');
        while (separator !== -1) {
          const frame = buffer.slice(0, separator);
          buffer = buffer.slice(separator + 2);
          separator = buffer.indexOf('\n\n');

          // A single SSE frame may contain multiple ``data:`` lines (the
          // spec concatenates them with newlines). Hospital Hotline only
          // emits one per frame, but handle the general case for safety.
          const dataLines = frame
            .split('\n')
            .filter((line) => line.startsWith('data:'))
            .map((line) => line.slice(5).trimStart());
          if (dataLines.length === 0) continue;
          const payloadStr = dataLines.join('\n');
          try {
            const event = JSON.parse(payloadStr) as ChatStreamEvent;
            yield event;
          } catch {
            // Drop frames we can't parse rather than throwing — a
            // truncated/proxy-mangled frame should never tear down the
            // whole stream.
          }
        }
      }
    } finally {
      try {
        reader.releaseLock();
      } catch {
        // ignore
      }
    }
  },

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

  listAssessmentReviews: (status: 'all' | 'pending' | 'approved' | 'corrected' = 'pending') =>
    request<AssessmentReviewOut[]>(`/admin/reviews?status=${status}`),

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

  // ── Disease Surveillance ───────────────────────────────────────────────────
  updateSessionLocation: (sessionId: string, payload: SessionLocationUpdate) =>
    request<{ session_id: string; location_area: string }>(
      `/sessions/${sessionId}/location`,
      { method: 'PUT', body: JSON.stringify(payload) },
    ),

  getSurveillanceSummary: (days = 7) =>
    request<SurveillanceSummaryOut>(`/admin/surveillance?days=${days}`),

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
};

export type { MessageOut, SessionOut, ConversationSummaryOut, DepartmentOut, DoctorOut, DoctorWithSchedulesOut, DoctorScheduleOut, SurveillanceSummaryOut, TriageManualUploadOut };
