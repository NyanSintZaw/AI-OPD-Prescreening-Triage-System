import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api';
import type { InputMode, MessageOut } from '../api/types';
import { createAIProvider } from '../ai';
import type { AIChatResponse } from '../ai/types';
import type { AppLanguage } from '../i18n/resources';

export interface ChatAssessment {
  severity?: AIChatResponse['severity'];
  department?: AIChatResponse['department'] & { name?: string };
  emergency?: AIChatResponse['emergency'];
  followUpQuestion?: string;
  followUpReason?: string;
  alertSent?: boolean;
}

export function useChat(sessionId: string | null, language: AppLanguage) {
  const [messages, setMessages] = useState<MessageOut[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [assessment, setAssessment] = useState<ChatAssessment | null>(null);
  const aiProvider = useMemo(() => createAIProvider(), []);
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
      if (!sessionId || !content.trim() || isSending) return;

      setIsSending(true);
      setError(null);

      try {
        const aiResponse = await aiProvider.generateReply({
          sessionId,
          language,
          inputMode,
          userMessage: content.trim(),
          history: messages,
        });

        const usingBackendOrchestration =
          (import.meta.env.VITE_AI_PROVIDER ?? 'http') === 'http';

        if (!usingBackendOrchestration) {
          const userMessage = await api.createMessage(sessionId, {
            role: 'user',
            input_mode: inputMode,
            content: content.trim(),
          });
          setMessages((prev) => [...prev, userMessage]);

          const assistantMessage = await api.createMessage(sessionId, {
            role: 'assistant',
            content: aiResponse.reply,
            model_name: aiResponse.modelName,
            response_latency_ms: aiResponse.latencyMs,
          });
          setMessages((prev) => [...prev, assistantMessage]);
        } else {
          await loadMessages();
        }

        const deptName = aiResponse.department?.departmentId
          ? departmentsRef.current.get(aiResponse.department.departmentId)
          : undefined;
        setAssessment({
          severity: aiResponse.severity,
          department: aiResponse.department
            ? { ...aiResponse.department, name: deptName }
            : undefined,
          emergency: aiResponse.emergency,
          followUpQuestion: aiResponse.followUpQuestion,
          followUpReason: aiResponse.followUpReason,
          alertSent: aiResponse.alertSent,
        });

        const assistantMessage = messages[messages.length - 1];
        return { aiResponse, assistantMessage };
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to send message');
        return null;
      } finally {
        setIsSending(false);
      }
    },
    [sessionId, isSending, aiProvider, language, messages, loadMessages],
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
