import type { ChatResponsePayload, SeverityLevel } from '../api/types';

export interface ChatAssessment {
  severity?: {
    level: SeverityLevel;
    explanation?: string;
    confidence?: number;
  };
  department?: {
    departmentId: string;
    reason?: string;
    confidence?: number;
    name?: string;
    code?: string;
    navLine?: string | null;
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
    painScore?: number;
    painLocation?: string;
    distressScore?: number;
    distressType?: string;
    redFlags?: string[];
  };
  followUpQuestion?: string;
  followUpReason?: string;
  alertSent?: boolean;
  modelName?: string;
  latencyMs?: number;
  assistantMessageId?: string;
  contact?: Record<string, unknown> | null;
  /** 'complete' once the rules engine has produced a routing decision. */
  assessmentStatus?: 'complete' | 'in_progress';
  /** Vital key (e.g. 'temp') the engine is asking the booth to measure now. */
  awaitingMeasurement?: string | null;
  /** Localized quick-reply chips under the last assistant bubble. */
  replyOptions?: Array<{ id: string; label: string }>;
  /** True when the patient-facing flow (incl. follow-up) is finished. */
  flowComplete?: boolean;
}

export function toAssessment(
  payload: ChatResponsePayload,
  departmentInfo: Map<string, { name: string; code: string; navLine?: string | null }>,
): ChatAssessment {
  const deptId = payload.department?.department_id;
  return {
    severity: payload.severity
      ? {
          level: payload.severity.level,
          explanation: payload.severity.explanation,
          confidence: payload.severity.confidence,
        }
      : undefined,
    department: deptId
      ? {
          departmentId: deptId,
          reason: payload.department?.reason,
          confidence: payload.department?.confidence,
          name: departmentInfo.get(deptId)?.name,
          code: departmentInfo.get(deptId)?.code,
          navLine: departmentInfo.get(deptId)?.navLine ?? null,
        }
      : undefined,
    emergency: payload.emergency
      ? {
          triggerId: payload.emergency.trigger_id,
          alertMessage: payload.emergency.alert_message,
          detectedSymptoms: payload.emergency.detected_symptoms,
        }
      : undefined,
    symptoms: payload.symptoms
      ? {
          rawText: payload.symptoms.raw_text,
          bodyLocation: payload.symptoms.body_location ?? undefined,
          durationText: payload.symptoms.duration_text ?? undefined,
          painScore: payload.symptoms.pain_score ?? undefined,
          painLocation: payload.symptoms.pain_location ?? undefined,
          distressScore: payload.symptoms.distress_score ?? undefined,
          distressType: payload.symptoms.distress_type ?? undefined,
          redFlags: payload.symptoms.red_flags ?? [],
        }
      : undefined,
    followUpQuestion: payload.follow_up_question ?? undefined,
    followUpReason: payload.follow_up_reason ?? undefined,
    alertSent: payload.alert_sent ?? false,
    modelName: payload.model_name ?? undefined,
    latencyMs: payload.latency_ms ?? undefined,
    assistantMessageId: payload.assistant_message_id ?? undefined,
    contact: payload.contact ?? undefined,
    assessmentStatus: payload.assessment_status ?? undefined,
    awaitingMeasurement: payload.awaiting_measurement ?? undefined,
    replyOptions: payload.reply_options ?? [],
    flowComplete: Boolean(payload.flow_complete),
  };
}
