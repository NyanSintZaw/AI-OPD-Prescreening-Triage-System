/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_AI_PROVIDER: 'stub' | 'http' | 'openai';
  readonly VITE_AI_CHAT_URL: string;
  readonly VITE_ENABLE_VOICE: string;
  readonly VITE_FRONTDESK_MODE: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
