import { AiOrb } from 'hospital-hotline-assistant-web';

export const Idle = () => <AiOrb state="idle" />;
export const Listening = () => <AiOrb state="listening" />;
export const Speaking = () => <AiOrb state="speaking" />;
export const Thinking = () => <AiOrb state="thinking" />;
export const Small = () => <AiOrb state="idle" size={72} />;
