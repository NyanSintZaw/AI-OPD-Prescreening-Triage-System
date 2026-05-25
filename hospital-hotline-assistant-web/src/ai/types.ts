import type { InputMode, LanguageCode, MessageOut, SeverityLevel } from '../api/types';

export interface AIChatRequest {
  sessionId: string;
  language: LanguageCode;
  inputMode: InputMode;
  userMessage: string;
  history: MessageOut[];
}

export interface AIChatResponse {
  reply: string;
  severity?: {
    level: SeverityLevel;
    explanation?: string;
    confidence?: number;
  };
  department?: {
    departmentId: string;
    reason?: string;
    confidence?: number;
  };
  emergency?: {
    triggerId?: string;
    alertMessage: string;
    detectedSymptoms?: string[];
  };
  symptoms?: {
    rawText: string;
    bodyLocation?: string;
    durationText?: string;
  };
  modelName?: string;
  latencyMs?: number;
  followUpQuestion?: string;
  followUpReason?: string;
  alertSent?: boolean;
  assistantMessageId?: string;
}

export interface AIProvider {
  generateReply(request: AIChatRequest): Promise<AIChatResponse>;
}
