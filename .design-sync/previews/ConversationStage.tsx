import { ConversationStage } from 'hospital-hotline-assistant-web';

const noop = () => {};

const Shell = ({ children }: { children?: any }) => (
  <div
    className="kiosk-root"
    // .kiosk-root is position:fixed inset:0 (full kiosk canvas) — pin it
    // back into the preview cell and let content size it.
    style={{ position: 'relative', overflow: 'visible', padding: 24 }}
  >
    {/* The capture harness freezes the clock (page.clock.setFixedTime), so
        framer-motion enter animations stall on their first frame (opacity 0).
        Force the settled end state — stylesheet !important beats framer's
        inline styles. */}
    <style>{`.k-conv .k-speech-text, .k-conv .k-chip { opacity: 1 !important; transform: none !important; }`}</style>
    {children}
  </div>
);

const base = {
  language: 'th' as const,
  onTapReply: noop,
  onDone: noop,
  onEnd: noop,
  onRetry: noop,
  onInterrupt: noop,
  onMeasurementSubmit: noop,
  measurementVital: null,
};

/** Mic live, severity question with tap-to-answer chips. */
export const ListeningWithChips = () => (
  <Shell>
    <ConversationStage
      {...base}
      state="listening"
      lastReply="อาการปวดหัวของคุณรุนแรงแค่ไหนคะ"
      lastTranscript="ปวดหัวมาตั้งแต่เมื่อวานค่ะ"
      replyOptions={[
        { id: 'opt-1', label: 'ปวดมาก' },
        { id: 'opt-2', label: 'ปวดปานกลาง' },
        { id: 'opt-3', label: 'ปวดเล็กน้อย' },
      ]}
    />
  </Shell>
);

/** Assistant reply playing — interrupt button visible for barge-in. */
export const AssistantSpeaking = () => (
  <Shell>
    <ConversationStage
      {...base}
      state="speaking"
      lastReply="ขอบคุณค่ะ มีไข้ร่วมด้วยไหมคะ หรือรู้สึกคลื่นไส้อาเจียนบ้างหรือเปล่า"
      lastTranscript="ปวดตุบ ๆ ข้างขวาค่ะ"
      replyOptions={[]}
      canInterrupt
    />
  </Shell>
);

/** Engine requested a temperature reading mid-interview → MeasurementCard. */
export const MeasurementRequest = () => (
  <Shell>
    <ConversationStage
      {...base}
      state="listening"
      lastReply="ขอทราบอุณหภูมิร่างกายหน่อยนะคะ ใช้เครื่องวัดข้างเครื่องได้เลยค่ะ"
      lastTranscript=""
      replyOptions={[]}
      measurementVital="temp"
    />
  </Shell>
);

/** Mic denied / connection dropped — plain error copy + big retry. */
export const MicError = () => (
  <Shell>
    <ConversationStage
      {...base}
      state="error"
      hasError
      lastReply=""
      lastTranscript=""
      replyOptions={[]}
    />
  </Shell>
);
