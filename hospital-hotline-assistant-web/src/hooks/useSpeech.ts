import { useCallback, useEffect, useRef, useState } from 'react';
import type { AppLanguage } from '../i18n/resources';

const voiceEnabled = import.meta.env.VITE_ENABLE_VOICE === 'true';

interface SpeechRecognitionEventLike {
  results: ArrayLike<{ 0: { transcript: string; confidence?: number } }>;
}

interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

function getSpeechRecognition(): (new () => SpeechRecognitionLike) | null {
  const w = window as Window & {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function useSpeechRecognition(language: AppLanguage) {
  const [isListening, setIsListening] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [confidence, setConfidence] = useState<number | null>(null);
  const [supported, setSupported] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  useEffect(() => {
    setSupported(voiceEnabled && getSpeechRecognition() !== null);
  }, []);

  const startListening = useCallback(() => {
    if (!voiceEnabled) return;

    const SpeechRecognition = getSpeechRecognition();
    if (!SpeechRecognition) return;

    const recognition = new SpeechRecognition();
    recognition.lang = language === 'th' ? 'th-TH' : 'en-US';
    recognition.continuous = false;
    recognition.interimResults = false;

    recognition.onresult = (event) => {
      const result = event.results[0]?.[0];
      if (result) {
        setTranscript(result.transcript);
        setConfidence(result.confidence ?? null);
      }
    };

    recognition.onerror = () => {
      setIsListening(false);
    };

    recognition.onend = () => {
      setIsListening(false);
    };

    recognitionRef.current = recognition;
    setIsListening(true);
    recognition.start();
  }, [language]);

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop();
    setIsListening(false);
  }, []);

  const clearTranscript = useCallback(() => {
    setTranscript('');
    setConfidence(null);
  }, []);

  return {
    isListening,
    transcript,
    confidence,
    supported,
    enabled: voiceEnabled,
    startListening,
    stopListening,
    clearTranscript,
  };
}

export function useSpeechSynthesis(language: AppLanguage) {
  const [enabled, setEnabled] = useState(false);
  const supported = typeof window !== 'undefined' && 'speechSynthesis' in window;

  const speak = useCallback(
    (text: string) => {
      if (!enabled || !supported || !text) return;

      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = language === 'th' ? 'th-TH' : 'en-US';
      utterance.rate = 0.95;
      window.speechSynthesis.speak(utterance);
    },
    [enabled, supported, language],
  );

  const stop = useCallback(() => {
    window.speechSynthesis.cancel();
  }, []);

  const toggle = useCallback(() => {
    setEnabled((prev) => !prev);
  }, []);

  return { enabled, supported, speak, stop, toggle, setEnabled };
}
