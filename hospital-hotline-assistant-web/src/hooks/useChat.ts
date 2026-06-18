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
}

export function toAssessment(
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
  };
}

export interface StreamingTurn {
  /** Optimistic user message (synthetic id until the server confirms). */
  userMessage: MessageOut;
  /** Live-updating assistant text accumulated from delta events. */
  assistantText: string;
  /** True once the server has emitted ``complete`` or ``error``. */
  done: boolean;
  /** Non-null only on ``error`` frames. */
  error: string | null;
}

export interface SendStreamCallbacks {
  /** Fired for every delta frame — useful for sentence-boundary TTS. */
  onDelta?: (chunk: string, full: string) => void;
  /**
   * Fired when the backend tells us a chunk we previously streamed
   * was actually pre-tool-call reasoning from one of the inner LLM
   * calls (Orchestrator routing, agent thinking before a tool
   * dispatch). The UI should wipe the assistant bubble and the TTS
   * queue so the next batch of deltas — the real reply — replaces
   * the discarded thinking.
   */
  onReset?: () => void;
  /** Fired exactly once when the server finishes the turn. */
  onComplete?: (response: ChatResponsePayload, assessment: ChatAssessment) => void;
  /** Fired on transport / server-reported errors. */
  onError?: (message: string) => void;
}

export function useChat(sessionId: string | null, language: AppLanguage) {
  const [messages, setMessages] = useState<MessageOut[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [assessment, setAssessment] = useState<ChatAssessment | null>(null);
  const [streamingTurn, setStreamingTurn] = useState<StreamingTurn | null>(null);
  const departmentsRef = useRef<Map<string, string>>(new Map());
  const abortRef = useRef<AbortController | null>(null);

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

  const sendMessageStream = useCallback(
    async (
      content: string,
      inputMode: InputMode = 'text',
      callbacks: SendStreamCallbacks = {},
    ) => {
      if (!sessionId || !content.trim() || isSending) return null;

      setIsSending(true);
      setError(null);

      // Cancel any prior in-flight stream (e.g. user spammed Enter).
      // Without this we'd race two SSE readers against each other and
      // the older one would happily keep pushing deltas into the
      // newer turn's UI bubble.
      if (abortRef.current) {
        abortRef.current.abort();
      }
      const controller = new AbortController();
      abortRef.current = controller;

      // Optimistic user bubble. We use a synthetic id prefixed with
      // "optim_" so the UI can distinguish it from server-confirmed
      // ones, but it carries the same MessageOut shape so the
      // existing renderers don't need branching. Once the server's
      // first ``user_message`` frame arrives we swap this id for the
      // real DB row's id (and timestamp).
      const trimmed = content.trim();
      const optimistic: MessageOut = {
        id: `optim_${Date.now()}`,
        session_id: sessionId,
        role: 'user',
        input_mode: inputMode,
        content: trimmed,
        created_at: new Date().toISOString(),
      };

      // Seed the streaming turn so the UI immediately shows the user
      // bubble + an empty assistant bubble. We append the optimistic
      // message into the rendered list right away (the assistant
      // bubble is rendered separately from ``streamingTurn`` so it
      // can live-update without re-rendering the message list).
      setMessages((prev) => [...prev, optimistic]);
      setStreamingTurn({
        userMessage: optimistic,
        assistantText: '',
        done: false,
        error: null,
      });

      let accumulated = '';
      let serverUserMessageId: string | null = null;

      try {
        for await (const event of api.chatStream(
          sessionId,
          {
            content: trimmed,
            input_mode: inputMode,
            language,
            history: [],
          },
          controller.signal,
        )) {
          if (event.type === 'user_message') {
            serverUserMessageId = event.message.id;
            // Swap the optimistic id for the real DB id so any future
            // operations (edit / delete / message references) work.
            setMessages((prev) =>
              prev.map((m) =>
                m.id === optimistic.id ? { ...event.message } : m,
              ),
            );
          } else if (event.type === 'delta') {
            accumulated += event.text;
            setStreamingTurn((prev) =>
              prev ? { ...prev, assistantText: accumulated } : prev,
            );
            callbacks.onDelta?.(event.text, accumulated);
          } else if (event.type === 'reset') {
            // Backend signal: the chunks we just streamed were
            // pre-tool-call thinking from one of the orchestrator's
            // inner LLM calls, not the real reply. Drop everything
            // so the bubble (and TTS queue) start clean on the next
            // delta batch.
            accumulated = '';
            setStreamingTurn((prev) =>
              prev ? { ...prev, assistantText: '' } : prev,
            );
            callbacks.onReset?.();
          } else if (event.type === 'turn_complete') {
            setMessages((prev) => {
              if (prev.some((m) => m.id === event.assistant_message.id)) {
                return prev;
              }
              return [...prev, event.assistant_message];
            });
            setStreamingTurn(null);
            callbacks.onComplete?.(
              {
                reply: event.assistant_message.content,
                severity: { level: 'unknown' },
                department: null,
                emergency: null,
                symptoms: null,
                follow_up_question: null,
                follow_up_reason: null,
                model_name: event.assistant_message.model_name ?? null,
                latency_ms: event.assistant_message.response_latency_ms ?? null,
                alert_sent: false,
                assistant_message_id: event.assistant_message.id,
              },
              {
                followUpQuestion: event.awaiting_contact
                  ? event.assistant_message.content
                  : undefined,
                assistantMessageId: event.assistant_message.id,
              },
            );
            return {
              response: null,
              assessment: null,
              userMessageId: serverUserMessageId,
            };
          } else if (event.type === 'complete') {
            const response = event.result;
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
                // non-fatal
              }
            }
            const nextAssessment = toAssessment(response, departmentsRef.current);
            setAssessment(nextAssessment);

            // Append the assistant message to the rendered list. We
            // dedupe in case loadMessages races us — the DB row's id
            // is the source of truth.
            setMessages((prev) => {
              if (prev.some((m) => m.id === event.assistant_message.id)) {
                return prev;
              }
              return [...prev, event.assistant_message];
            });
            setStreamingTurn(null);
            callbacks.onComplete?.(response, nextAssessment);
            return {
              response,
              assessment: nextAssessment,
              userMessageId: serverUserMessageId,
            };
          } else if (event.type === 'error') {
            setError(event.message);
            setStreamingTurn((prev) =>
              prev ? { ...prev, done: true, error: event.message } : prev,
            );
            callbacks.onError?.(event.message);
            return null;
          }
        }
        // Stream ended without a ``complete`` frame — surface as an error.
        const msg = 'Stream ended unexpectedly';
        setError(msg);
        setStreamingTurn((prev) =>
          prev ? { ...prev, done: true, error: msg } : prev,
        );
        callbacks.onError?.(msg);
        return null;
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') {
          return null;
        }
        const message = err instanceof Error ? err.message : 'Failed to send message';
        setError(message);
        setStreamingTurn((prev) =>
          prev ? { ...prev, done: true, error: message } : prev,
        );
        callbacks.onError?.(message);
        return null;
      } finally {
        setIsSending(false);
        if (abortRef.current === controller) {
          abortRef.current = null;
        }
      }
    },
    [sessionId, isSending, language],
  );

  // Tear down any in-flight stream when the hook unmounts (e.g. user
  // navigates back to the landing page mid-response).
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  return {
    messages,
    isLoading,
    isSending,
    error,
    assessment,
    streamingTurn,
    loadMessages,
    sendMessage,
    sendMessageStream,
    setAssessment,
  };
}
