import { request } from './client';
import type {
  ChatRequestPayload,
  ChatResponsePayload,
  ConversationSummaryOut,
  DepartmentOut,
  DepartmentRecommendationCreate,
  EmergencyEventOut,
  EmergencyEventCreate,
  EmergencyTriggerOut,
  FollowUpQuestionOut,
  MessageCreate,
  MessageOut,
  RoutingRuleOut,
  SessionCreate,
  SessionOut,
  SessionUpdate,
  SeverityAssessmentCreate,
  SymptomEntryCreate,
} from './types';

export const api = {
  health: () => request<{ status: string; environment: string }>('/health'),

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
};

export type { MessageOut, SessionOut, ConversationSummaryOut, DepartmentOut };
