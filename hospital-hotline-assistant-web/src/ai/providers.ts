import type { AIProvider, AIChatRequest, AIChatResponse } from './types';

const DEMO_EMERGENCY_KEYWORDS = ['chest pain', 'เจ็บหน้าอก'];

function containsEmergencyKeyword(text: string): boolean {
  const lower = text.toLowerCase();
  return DEMO_EMERGENCY_KEYWORDS.some((keyword) => lower.includes(keyword));
}

export class StubAIProvider implements AIProvider {
  async generateReply(request: AIChatRequest): Promise<AIChatResponse> {
    await delay(800);

    const isTh = request.language === 'th';
    const isEmergency = containsEmergencyKeyword(request.userMessage);

    if (isEmergency) {
      return {
        reply: isTh
          ? 'อาการที่คุณอธิบายอาจเป็นภาวะฉุกเฉิน กรุณารีบไปพบแพทย์ทันทีหรือติดต่อหน่วยฉุกเฉิน ระบบ AI จริงจะให้คำแนะนำเพิ่มเติมเมื่อเชื่อมต่อแล้ว'
          : 'Based on what you described, this may be an emergency. Please seek immediate medical care or contact emergency services. The real AI service will provide full guidance once connected.',
        severity: {
          level: 'emergency',
          explanation: isTh
            ? 'ตรวจพบอาการที่อาจเป็นเหตุฉุกเฉิน (demo stub)'
            : 'Possible emergency symptoms detected (demo stub)',
          confidence: 0.85,
        },
        emergency: {
          alertMessage: isTh
            ? 'อาการนี้อาจเป็นภาวะฉุกเฉิน กรุณารีบไปพบแพทย์ทันทีหรือติดต่อหน่วยฉุกเฉิน'
            : 'This may be an emergency. Please seek immediate medical care or contact emergency services.',
          detectedSymptoms: [request.userMessage],
        },
        modelName: 'stub-provider',
        latencyMs: 800,
      };
    }

    return {
      reply: isTh
        ? 'ขอบคุณที่แจ้งอาการของคุณ ระบบ AI กำลังอยู่ระหว่างการเชื่อมต่อ ขณะนี้เป็นข้อความตัวอย่างจาก stub provider ทีม AI จะเชื่อมต่อบริการจริงในภายหลัง'
        : 'Thank you for describing your symptoms. The AI service is not connected yet — this is a placeholder response from the stub provider. Your AI engineer can plug in the real service later.',
      severity: {
        level: 'unknown',
        explanation: isTh ? 'รอการประเมินจาก AI' : 'Awaiting AI assessment',
      },
      modelName: 'stub-provider',
      latencyMs: 800,
    };
  }
}

export class HttpAIProvider implements AIProvider {
  private url: string;

  constructor(url: string) {
    this.url = url;
  }

  async generateReply(request: AIChatRequest): Promise<AIChatResponse> {
    const response = await fetch(this.url.replace('{sessionId}', request.sessionId), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        content: request.userMessage,
        input_mode: request.inputMode,
        language: request.language,
        history: request.history,
      }),
    });

    if (!response.ok) {
      throw new Error(`AI service error: ${response.statusText}`);
    }

    const payload = (await response.json()) as {
      reply: string;
      severity?: { level: 'emergency' | 'urgent' | 'general' | 'unknown'; explanation?: string; confidence?: number };
      department?: { department_id?: string; reason?: string; confidence?: number } | null;
      emergency?: { trigger_id?: string; alert_message: string; detected_symptoms?: string[] } | null;
      symptoms?: { raw_text: string; body_location?: string; duration_text?: string } | null;
      follow_up_question?: string | null;
      follow_up_reason?: string | null;
      model_name?: string | null;
      latency_ms?: number | null;
      alert_sent?: boolean;
      assistant_message_id?: string | null;
    };

    return {
      reply: payload.reply,
      severity: payload.severity,
      department: payload.department?.department_id
        ? {
            departmentId: payload.department.department_id,
            reason: payload.department.reason,
            confidence: payload.department.confidence,
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
      modelName: payload.model_name ?? undefined,
      latencyMs: payload.latency_ms ?? undefined,
      alertSent: payload.alert_sent ?? false,
      assistantMessageId: payload.assistant_message_id ?? undefined,
    };
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function createAIProvider(): AIProvider {
  const provider = import.meta.env.VITE_AI_PROVIDER ?? 'http';
  const chatUrl = import.meta.env.VITE_AI_CHAT_URL ?? '';

  if (provider === 'http' && chatUrl) {
    return new HttpAIProvider(chatUrl);
  }

  return new StubAIProvider();
}
