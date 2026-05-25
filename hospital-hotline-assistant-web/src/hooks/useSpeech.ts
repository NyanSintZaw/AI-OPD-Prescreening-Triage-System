import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { AppLanguage } from '../i18n/resources';

const voiceFeatureEnabled = import.meta.env.VITE_ENABLE_VOICE === 'true';

function pickMediaRecorderMimeType(): string | undefined {
  if (typeof MediaRecorder === 'undefined') return undefined;
  const preferences = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    'audio/ogg',
    'audio/mp4',
    'audio/mpeg',
  ];
  for (const candidate of preferences) {
    if (MediaRecorder.isTypeSupported(candidate)) {
      return candidate;
    }
  }
  return undefined;
}

export function useSpeechRecognition(language: AppLanguage) {
  const [isListening, setIsListening] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [confidence, setConfidence] = useState<number | null>(null);
  const [supported, setSupported] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  useEffect(() => {
    const hasMedia =
      typeof navigator !== 'undefined' &&
      typeof navigator.mediaDevices?.getUserMedia === 'function' &&
      typeof MediaRecorder !== 'undefined';
    setSupported(voiceFeatureEnabled && hasMedia);
  }, []);

  const cleanupStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const startListening = useCallback(async () => {
    if (!voiceFeatureEnabled || !supported) return;
    if (recorderRef.current) return;

    setError(null);
    setTranscript('');
    setConfidence(null);

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Microphone access denied');
      return;
    }

    streamRef.current = stream;
    const mimeType = pickMediaRecorderMimeType();
    const recorder = mimeType
      ? new MediaRecorder(stream, { mimeType })
      : new MediaRecorder(stream);
    recorderRef.current = recorder;
    chunksRef.current = [];

    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        chunksRef.current.push(event.data);
      }
    };

    recorder.onstop = async () => {
      const blobType = recorder.mimeType || mimeType || 'audio/webm';
      const audioBlob = new Blob(chunksRef.current, { type: blobType });
      chunksRef.current = [];
      cleanupStream();
      recorderRef.current = null;
      setIsListening(false);

      if (audioBlob.size === 0) {
        setError('No audio captured');
        return;
      }

      try {
        const result = await api.stt(audioBlob, language, fileNameForMime(blobType));
        setTranscript(result.transcript);
        setConfidence(result.confidence);
        if (!result.transcript) {
          setError('Could not understand the audio. Please try again.');
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Transcription failed');
      }
    };

    recorder.start();
    setIsListening(true);
  }, [supported, language, cleanupStream]);

  const stopListening = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop();
    } else {
      cleanupStream();
      setIsListening(false);
    }
  }, [cleanupStream]);

  const clearTranscript = useCallback(() => {
    setTranscript('');
    setConfidence(null);
    setError(null);
  }, []);

  useEffect(() => {
    return () => {
      if (recorderRef.current && recorderRef.current.state !== 'inactive') {
        recorderRef.current.stop();
      }
      cleanupStream();
    };
  }, [cleanupStream]);

  return {
    isListening,
    transcript,
    confidence,
    supported,
    enabled: voiceFeatureEnabled,
    error,
    startListening,
    stopListening,
    clearTranscript,
  };
}

function fileNameForMime(mime: string): string {
  if (mime.includes('webm')) return 'speech.webm';
  if (mime.includes('ogg')) return 'speech.ogg';
  if (mime.includes('mp4')) return 'speech.mp4';
  if (mime.includes('mpeg')) return 'speech.mp3';
  if (mime.includes('wav')) return 'speech.wav';
  return 'speech.bin';
}

export function useSpeechSynthesis(language: AppLanguage) {
  const [enabled, setEnabled] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const lastUrlRef = useRef<string | null>(null);

  const supported = typeof window !== 'undefined' && typeof Audio !== 'undefined';

  const stop = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = '';
      audioRef.current = null;
    }
    if (lastUrlRef.current) {
      URL.revokeObjectURL(lastUrlRef.current);
      lastUrlRef.current = null;
    }
    setIsSpeaking(false);
  }, []);

  const speak = useCallback(
    async (text: string) => {
      if (!enabled || !supported || !text.trim()) return;

      stop();
      setError(null);
      setIsSpeaking(true);

      try {
        const blob = await api.tts(text, language);
        const url = URL.createObjectURL(blob);
        lastUrlRef.current = url;
        const audio = new Audio(url);
        audioRef.current = audio;
        audio.onended = () => {
          setIsSpeaking(false);
          if (lastUrlRef.current) {
            URL.revokeObjectURL(lastUrlRef.current);
            lastUrlRef.current = null;
          }
        };
        audio.onerror = () => {
          setError('Audio playback failed');
          setIsSpeaking(false);
        };
        await audio.play();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Text-to-speech failed');
        setIsSpeaking(false);
      }
    },
    [enabled, supported, language, stop],
  );

  const toggle = useCallback(() => {
    setEnabled((prev) => !prev);
  }, []);

  useEffect(() => {
    return () => {
      stop();
    };
  }, [stop]);

  return {
    enabled,
    supported,
    isSpeaking,
    error,
    speak,
    stop,
    toggle,
    setEnabled,
  };
}
