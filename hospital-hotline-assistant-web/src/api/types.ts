export type LanguageCode = 'th' | 'en';
export type SessionStatus = 'active' | 'completed' | 'reset' | 'escalated';
export type MessageRole = 'user' | 'assistant' | 'system';
export type InputMode = 'voice' | 'text';
export type SeverityLevel = 'emergency' | 'urgent' | 'general' | 'unknown';
export type DepartmentKind = 'emergency' | 'opd';
export type ReviewStatus = 'pending' | 'approved' | 'corrected';

export interface SessionCreate {
  language?: LanguageCode;
  user_agent?: string | null;
  ip_hash?: string | null;
  metadata?: Record<string, unknown>;
}

export interface SessionUpdate {
  status: SessionStatus;
}

export interface SessionOut {
  id: string;
  language: LanguageCode;
  status: SessionStatus;
  started_at: string;
  ended_at: string | null;
  user_agent: string | null;
  ip_hash: string | null;
  metadata: Record<string, unknown>;
}

export interface MessageCreate {
  role: MessageRole;
  input_mode?: InputMode | null;
  content: string;
  audio_url?: string | null;
  transcript_confidence?: number | null;
  model_name?: string | null;
  response_latency_ms?: number | null;
  metadata?: Record<string, unknown>;
}

export interface MessageOut extends MessageCreate {
  id: string;
  session_id: string;
  created_at: string;
}

export interface SymptomEntryCreate {
  message_id?: string | null;
  raw_text: string;
  normalized_symptoms?: unknown[];
  body_location?: string | null;
  duration_text?: string | null;
  pain_score?: number | null;
  pain_location?: string | null;
  distress_score?: number | null;
  distress_type?: string | null;
  red_flags?: string[];
}

export interface SeverityAssessmentCreate {
  source_message_id?: string | null;
  severity?: SeverityLevel;
  confidence?: number | null;
  explanation?: string | null;
  detected_triggers?: unknown[];
}

export interface DepartmentOut {
  id: string;
  code: string;
  kind: DepartmentKind;
  name_en: string;
  name_th: string | null;
  description_en: string | null;
  description_th: string | null;
  is_active: boolean;
}

export interface RoutingRuleOut {
  id: string;
  department_id: string;
  rule_name: string;
  description: string | null;
  symptom_keywords: string[];
  condition_json: Record<string, unknown>;
  severity_override: SeverityLevel | null;
  priority: number;
  is_active: boolean;
}

export interface EmergencyTriggerOut {
  id: string;
  trigger_name: string;
  description: string | null;
  trigger_keywords: string[];
  condition_json: Record<string, unknown>;
  alert_message_en: string;
  alert_message_th: string | null;
  priority: number;
  is_active: boolean;
}

export interface DepartmentRecommendationCreate {
  assessment_id?: string | null;
  department_id: string;
  confidence?: number | null;
  reason?: string | null;
}

export interface EmergencyEventCreate {
  trigger_id?: string | null;
  source_message_id?: string | null;
  detected_symptoms?: unknown[];
  alert_message: string;
}

export interface ConversationSummaryOut {
  session_id: string;
  language: LanguageCode;
  status: SessionStatus;
  started_at: string;
  ended_at: string | null;
  severity: SeverityLevel | null;
  department_name_en: string | null;
  department_name_th: string | null;
  message_count: number;
  has_alert: boolean;
  escalation_reason: string | null;
}

export interface AdminUserOut {
  id: string;
  email: string;
  full_name: string | null;
  role: 'super_admin' | 'admin' | 'viewer';
}

export interface AdminLoginRequest {
  email: string;
  password: string;
}

export interface AdminLoginResponse {
  access_token: string;
  token_type: 'bearer';
  expires_at: string;
  user: AdminUserOut;
}

export interface AssessmentReviewOut {
  id: string;
  session_id: string;
  assessment_id: string;
  status: ReviewStatus;
  reviewer_id: string | null;
  reviewer_name: string | null;
  proposed_department_id: string | null;
  proposed_department_name_en: string | null;
  proposed_department_name_th: string | null;
  confirmed_department_id: string | null;
  confirmed_department_name_en: string | null;
  confirmed_department_name_th: string | null;
  ai_assessment_score: number | null;
  ai_assessment_scale: number;
  patient_contact_requested: boolean | null;
  patient_contact_phone: string | null;
  patient_contact_preferred_time: string | null;
  patient_contact_relation: string | null;
  notes: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AssessmentReviewApproveRequest {
  notes?: string | null;
  ai_assessment_score?: number | null;
}

export interface AssessmentReviewCorrectRequest {
  confirmed_department_id: string;
  reason?: string | null;
  ai_assessment_score?: number | null;
}

export interface RoutingFeedbackOut {
  id: string;
  session_id: string;
  assessment_id: string;
  original_department_id: string | null;
  corrected_department_id: string;
  corrected_department_name_en: string | null;
  corrected_department_name_th: string | null;
  reported_by: string | null;
  reporter_name: string | null;
  reason: string | null;
  created_at: string;
}

export interface ChatRequestPayload {
  content: string;
  input_mode: InputMode;
  language: LanguageCode;
  history?: Array<Record<string, unknown>>;
}

export interface ChatResponsePayload {
  reply: string;
  severity: {
    level: SeverityLevel;
    explanation?: string;
    confidence?: number;
  };
  department?: {
    department_id?: string;
    reason?: string;
    confidence?: number;
  } | null;
  emergency?: {
    trigger_id?: string;
    alert_message: string;
    detected_symptoms?: string[];
  } | null;
  symptoms?: {
    raw_text: string;
    body_location?: string | null;
    duration_text?: string | null;
    pain_score?: number | null;
    pain_location?: string | null;
    distress_score?: number | null;
    distress_type?: string | null;
    red_flags?: string[];
  } | null;
  contact?: Record<string, unknown> | null;
  follow_up_question?: string | null;
  follow_up_reason?: string | null;
  model_name?: string | null;
  latency_ms?: number | null;
  alert_sent?: boolean;
  assistant_message_id?: string | null;
}

export interface FollowUpQuestionOut {
  id: string;
  session_id: string;
  question_text: string;
  reason: string | null;
  asked_at: string;
  answer_message_id: string | null;
  answered_at: string | null;
}

export interface EmergencyEventOut {
  id: string;
  session_id: string;
  trigger_id?: string | null;
  source_message_id?: string | null;
  detected_symptoms: unknown[];
  alert_message: string;
  created_at: string;
}

export interface SttResponsePayload {
  transcript: string;
  confidence: number | null;
  language_code: string;
}

/**
 * One frame emitted by ``POST /sessions/{id}/chat/stream``. The shape
 * mirrors :meth:`triage_service.process_chat_stream` — every frame
 * carries a ``type`` discriminator and the payload fields it needs.
 *
 * Frame ordering for a successful turn:
 *   1. ``user_message`` (once, with the persisted DB row)
 *   2. zero or more ``delta`` frames (typewriter text)
 *   3. zero or one ``classified`` frame (TriageAgent classified)
 *   4. ``complete`` (once, with full assessment + assistant DB row)
 * Errors interrupt with a single ``error`` frame.
 */
export type ChatStreamEvent =
  | { type: 'user_message'; message: MessageOut }
  | { type: 'delta'; text: string }
  | { type: 'reset' }
  | { type: 'classified'; classification: Record<string, unknown> }
  | {
      type: 'turn_complete';
      assistant_message: MessageOut;
      awaiting_contact?: boolean;
    }
  | {
      type: 'complete';
      result: ChatResponsePayload;
      assistant_message: MessageOut;
    }
  | { type: 'error'; message: string };

export interface ApiError {
  detail: string;
}
