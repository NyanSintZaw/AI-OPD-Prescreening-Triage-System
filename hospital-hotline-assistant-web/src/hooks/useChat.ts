import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type {
  ChatResponsePayload,
  InputMode,
  MessageOut,
  SeverityLevel,
} from '../api/types';
import type { AppLanguage } from '../i18n/resources';

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
  followUpQuestion?: string;
  followUpReason?: string;
  alertSent?: boolean;
  modelName?: string;
  latencyMs?: number;
  assistantMessageId?: string;
}

function toAssessment(
  payload: ChatResponsePayload,
  departmentNames: Map<string, string>,
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
          name: departmentNames.get(deptId),
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
          bodyLocation: payload.symptoms.body_location,
          durationText: payload.symptoms.duration_text,
        }
      : undefined,
    followUpQuestion: payload.follow_up_question ?? undefined,
    followUpReason: payload.follow_up_reason ?? undefined,
    alertSent: payload.alert_sent ?? false,
    modelName: payload.model_name ?? undefined,
    latencyMs: payload.latency_ms ?? undefined,
    assistantMessageId: payload.assistant_message_id ?? undefined,
  };
}

export function useChat(sessionId: string | null, language: AppLanguage) {
  const [messages, setMessages] = useState<MessageOut[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [assessment, setAssessment] = useState<ChatAssessment | null>(null);
  const departmentsRef = useRef<Map<string, string>>(new Map());

  useEffect(() => {
    setMessages([]);
    setAssessment(null);
    setError(null);
  }, [sessionId]);

  const loadMessages = useCallback(async () => {
    if (!sessionId) return;
    setIsLoading(true);
    setError(null);
    try {
      const [msgs, departments] = await Promise.all([
        api.listMessages(sessionId),
        api.listDepartments(),
      ]);
      departmentsRef.current = new Map(
        departments.map((d) => [d.id, language === 'th' ? d.name_th ?? d.name_en : d.name_en]),
      );
      setMessages(msgs);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load messages');
    } finally {
      setIsLoading(false);
    }
  }, [sessionId, language]);

  const sendMessage = useCallback(
    async (content: string, inputMode: InputMode = 'text') => {
      if (!sessionId || !content.trim() || isSending) return null;

      setIsSending(true);
      setError(null);

      try {
        const response = await api.chat(sessionId, {
          content: content.trim(),
          input_mode: inputMode,
          language,
          history: [],
        });

        if (departmentsRef.current.size === 0) {
          try {
            const departments = await api.listDepartments();
            departmentsRef.current = new Map(
              departments.map((d) => [
                d.id,
                language === 'th' ? d.name_th ?? d.name_en : d.name_en,
              ]),
            );
          } catch {
            // non-fatal; name will fall back to the id in the UI
          }
        }

        await loadMessages();

        const nextAssessment = toAssessment(response, departmentsRef.current);
        setAssessment(nextAssessment);
        return { response, assessment: nextAssessment };
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to send message');
        return null;
      } finally {
        setIsSending(false);
      }
    },
    [sessionId, isSending, language, loadMessages],
  );

  return {
    messages,
    isLoading,
    isSending,
    error,
    assessment,
    loadMessages,
    sendMessage,
    setAssessment,
  };
}
