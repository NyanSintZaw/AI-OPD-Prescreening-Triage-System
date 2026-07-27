import { MessageBubble } from 'hospital-hotline-assistant-web';

const base = { id: '1', session_id: 's1', created_at: '2026-07-24T09:00:00Z' };

export const PatientVoiceThai = () => (
  <div style={{ maxWidth: 420 }}>
    <MessageBubble
      message={{ ...base, role: 'user', input_mode: 'voice', content: 'มีไข้และปวดหัวมาสองวันค่ะ' }}
    />
  </div>
);

export const AssistantReply = () => (
  <div style={{ maxWidth: 420 }}>
    <MessageBubble
      message={{
        ...base,
        role: 'assistant',
        content: 'ขอบคุณค่ะ ไข้ขึ้นมาประมาณสองวันนะคะ มีอาการคลื่นไส้หรืออาเจียนร่วมด้วยไหมคะ',
      }}
    />
  </div>
);

export const ButtonReply = () => (
  <div style={{ maxWidth: 420 }}>
    <MessageBubble message={{ ...base, role: 'user', input_mode: 'button', content: 'ไม่มี' }} />
  </div>
);

export const EnglishTyped = () => (
  <div style={{ maxWidth: 420 }}>
    <MessageBubble
      message={{ ...base, role: 'user', input_mode: 'text', content: 'I have had a sore throat since yesterday.' }}
    />
  </div>
);
