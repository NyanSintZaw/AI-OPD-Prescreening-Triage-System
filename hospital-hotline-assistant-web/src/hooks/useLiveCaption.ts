import { useEffect, useRef, useState } from 'react';
import type { AppLanguage } from '../i18n/resources';

/**
 * Live caption preview of the patient's own speech via the browser
 * Web Speech API (Chrome's webkitSpeechRecognition — the kiosk browser).
 *
 * The authoritative turn text still comes from the server's one-shot STT
 * at end-of-turn (the voice pipeline is turn-based); this hook only gives
 * the patient immediate "we're hearing you" feedback while they talk.
 * On browsers without the API it degrades silently to an empty string —
 * the preview is never load-bearing.
 */

// Minimal typings for the (still-prefixed) Web Speech API.
interface SpeechRecognitionLike {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
}

interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: ArrayLike<{ 0: { transcript: string }; isFinal: boolean }>;
}

function getRecognitionCtor(): (new () => SpeechRecognitionLike) | null {
  if (typeof window === 'undefined') return null;
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function useLiveCaption(language: AppLanguage, active: boolean): string {
  const [caption, setCaption] = useState('');
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const activeRef = useRef(false);

  useEffect(() => {
    activeRef.current = active;
    if (!active) {
      setCaption('');
      const rec = recognitionRef.current;
      recognitionRef.current = null;
      if (rec) {
        rec.onresult = null;
        rec.onend = null;
        rec.onerror = null;
        try {
          rec.abort();
        } catch {
          // ignore
        }
      }
      return;
    }

    const Ctor = getRecognitionCtor();
    if (!Ctor) return;

    let disposed = false;
    const startRecognition = () => {
      if (disposed || !activeRef.current) return;
      const rec = new Ctor();
      rec.lang = language === 'th' ? 'th-TH' : 'en-US';
      rec.interimResults = true;
      rec.continuous = true;
      rec.onresult = (event) => {
        let text = '';
        for (let i = 0; i < event.results.length; i++) {
          text += event.results[i][0].transcript;
        }
        setCaption(text.trim());
      };
      // Chrome ends recognition spontaneously after silence — restart
      // while we're still supposed to be listening.
      rec.onend = () => {
        if (!disposed && activeRef.current && recognitionRef.current === rec) {
          recognitionRef.current = null;
          startRecognition();
        }
      };
      rec.onerror = () => {
        // 'no-speech', 'audio-capture', 'not-allowed', … — the preview is
        // best-effort; onend fires after and handles the restart.
      };
      recognitionRef.current = rec;
      try {
        rec.start();
      } catch {
        recognitionRef.current = null;
      }
    };

    startRecognition();
    return () => {
      disposed = true;
      const rec = recognitionRef.current;
      recognitionRef.current = null;
      if (rec) {
        rec.onresult = null;
        rec.onend = null;
        rec.onerror = null;
        try {
          rec.abort();
        } catch {
          // ignore
        }
      }
    };
  }, [active, language]);

  return active ? caption : '';
}
