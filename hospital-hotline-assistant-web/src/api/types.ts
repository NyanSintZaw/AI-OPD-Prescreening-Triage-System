export type LanguageCode = 'th' | 'en';
export type SessionStatus = 'active' | 'completed' | 'reset' | 'escalated';
export type MessageRole = 'user' | 'assistant' | 'system';
export type InputMode = 'voice' | 'text';
export type SeverityLevel = 'emergency' | 'urgent' | 'general' | 'unknown';

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
    body_location?: string;
    duration_text?: string;
  } | null;
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

export interface ApiError {
  detail: string;
}
