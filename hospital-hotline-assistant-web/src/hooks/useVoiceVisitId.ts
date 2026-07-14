import { useCallback, useRef, useState } from 'react';
import { api } from '../api';
import type { AppLanguage } from '../i18n/resources';

export type VoiceVisitState = 'idle' | 'recording' | 'processing';

// Thai spoken number words → digit, plus Thai numerals ๐–๙.
const TH_WORD_TO_DIGIT: Record<string, string> = {
  ศูนย์: '0',
  หนึ่ง: '1',
  เอ็ด: '1',
  สอง: '2',
  สาม: '3',
  สี่: '4',
  ห้า: '5',
  หก: '6',
  เจ็ด: '7',
  แปด: '8',
  เก้า: '9',
};
const TH_NUMERALS = '๐๑๒๓๔๕๖๗๘๙';

/**
 * Extract a numeric Visit ID from a speech transcript. Handles Arabic digits
 * ("990 000 001"), Thai numerals (๙๙๐…), and Thai spoken number words
 * ("เก้า เก้า ศูนย์…"). Everything non-numeric is dropped.
 */
export function parseSpokenDigits(transcript: string): string {
  let text = transcript;
  // Normalise Thai numerals to Arabic.
  text = text.replace(/[๐-๙]/g, (c) => String(TH_NUMERALS.indexOf(c)));
  // Replace Thai number words.
  for (const [word, digit] of Object.entries(TH_WORD_TO_DIGIT)) {
    text = text.split(word).join(digit);
  }
  // Keep only digits.
  return text.replace(/\D+/g, '');
}

/**
 * One-shot microphone capture for the Visit ID step. Tap to start, tap to
 * stop; on stop the audio is sent to the backend `/stt` endpoint (Google STT,
 * reliable for Thai) and the spoken digits are parsed out. Reuses the same
 * getUserMedia/MediaRecorder pattern as the live voice call but without the
 * streaming pipeline.
 */
export function useVoiceVisitId(language: AppLanguage) {
  const [state, setState] = useState<VoiceVisitState>('idle');
  const [error, setError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  const supported =
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== 'undefined';

  const cleanupStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  const start = useCallback(async () => {
    setError(null);
    if (!supported) {
      setError('unsupported');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      chunksRef.current = [];
      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorderRef.current = recorder;
      recorder.start();
      setState('recording');
    } catch {
      cleanupStream();
      setError('mic');
      setState('idle');
    }
  }, [supported, cleanupStream]);

  /** Stop recording, transcribe, and resolve with parsed digits ('' if none). */
  const stop = useCallback(async (): Promise<string> => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === 'inactive') {
      setState('idle');
      return '';
    }
    setState('processing');
    const audioBlob = await new Promise<Blob>((resolve) => {
      recorder.onstop = () => resolve(new Blob(chunksRef.current, { type: 'audio/webm' }));
      recorder.stop();
    });
    cleanupStream();
    try {
      const result = await api.stt(audioBlob, language, 'visit-id.webm');
      const digits = parseSpokenDigits(result.transcript ?? '');
      setState('idle');
      return digits;
    } catch {
      setError('stt');
      setState('idle');
      return '';
    }
  }, [language, cleanupStream]);

  const cancel = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== 'inactive') {
      recorder.onstop = null;
      recorder.stop();
    }
    cleanupStream();
    setState('idle');
  }, [cleanupStream]);

  return { state, error, supported, start, stop, cancel };
}
