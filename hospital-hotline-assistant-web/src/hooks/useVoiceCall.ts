import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { AppLanguage } from '../i18n/resources';

export type VoiceCallState =
  | 'idle'
  | 'starting'
  | 'greeting'
  | 'listening'
  | 'uploading'
  | 'thinking'
  | 'speaking'
  | 'error';

export interface UseVoiceCallOptions {
  language: AppLanguage;
  onTranscript: (transcript: string) => Promise<string | null | undefined>;
  /**
   * Optional scripted line the assistant speaks immediately after the call
   * connects, before the mic opens for the first user turn. Use this for the
   * hotline-style "Hello, this is ..." greeting.
   */
  initialGreeting?: string;
  /**
   * Optional callback fired right before the greeting is played, so the
   * caller can persist it (e.g. POST /sessions/{id}/messages) and update
   * any caption state. Fire-and-forget — errors are swallowed.
   */
  onGreeting?: (text: string) => void | Promise<void>;
}

interface UseVoiceCallApi {
  state: VoiceCallState;
  active: boolean;
  supported: boolean;
  error: string | null;
  lastTranscript: string;
  lastReply: string;
  start: () => Promise<void>;
  end: () => void;
}

const voiceFeatureEnabled = import.meta.env.VITE_ENABLE_VOICE === 'true';

// VAD tuning — natural-speech friendly with hysteresis + noise-floor calibration.
// Hysteresis means we use one threshold to *enter* speech state and a lower one
// to *leave* it. That avoids flapping when RMS bounces around a single
// threshold mid-sentence (which was cutting users off when they paused).
const VAD_SAMPLE_INTERVAL_MS = 40;
const SPEECH_RMS_THRESHOLD = 0.012; // enter "speaking" state
const SILENCE_RMS_THRESHOLD = 0.006; // leave "speaking" state (must drop below this)
const SILENCE_HANGOVER_MS = 1500; // how long quiet must persist after a phrase
const MAX_UTTERANCE_MS = 30_000;
const MIN_UTTERANCE_MS = 350;
const NO_SPEECH_TIMEOUT_MS = 10_000;
const NOISE_CALIBRATION_MS = 300; // measure ambient noise on each listen start
const NOISE_MULTIPLIER_SPEECH = 2.2; // require this much above noise floor to count as speech
const NOISE_MULTIPLIER_SILENCE = 1.3; // and this much above noise floor to stay in speech

function pickMediaRecorderMimeType(): string | undefined {
  if (typeof MediaRecorder === 'undefined') return undefined;
  const preferences = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    'audio/ogg',
    'audio/mp4',
  ];
  for (const candidate of preferences) {
    if (MediaRecorder.isTypeSupported(candidate)) return candidate;
  }
  return undefined;
}

function fileNameForMime(mime: string): string {
  if (mime.includes('webm')) return 'speech.webm';
  if (mime.includes('ogg')) return 'speech.ogg';
  if (mime.includes('mp4')) return 'speech.mp4';
  if (mime.includes('wav')) return 'speech.wav';
  return 'speech.bin';
}

/**
 * Continuous voice-call hook: mic auto-opens after each AI reply,
 * client-side voice-activity detection auto-stops on silence,
 * round-trips through /stt -> /chat -> /tts, then re-opens the mic.
 */
export function useVoiceCall(options: UseVoiceCallOptions): UseVoiceCallApi {
  const { language, onTranscript, initialGreeting, onGreeting } = options;

  const [state, setState] = useState<VoiceCallState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [lastTranscript, setLastTranscript] = useState('');
  const [lastReply, setLastReply] = useState('');
  const [supported, setSupported] = useState(false);

  // Refs are used so async callbacks always see the latest values
  // without forcing the start/end functions to re-create.
  const stateRef = useRef<VoiceCallState>('idle');
  const activeRef = useRef(false);
  const generationRef = useRef(0);
  const languageRef = useRef(language);
  const onTranscriptRef = useRef(onTranscript);
  const initialGreetingRef = useRef(initialGreeting);
  const onGreetingRef = useRef(onGreeting);

  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const vadIntervalRef = useRef<number | null>(null);
  const maxDurationTimerRef = useRef<number | null>(null);
  const noSpeechTimerRef = useRef<number | null>(null);
  const playingAudioRef = useRef<HTMLAudioElement | null>(null);
  const playingAudioUrlRef = useRef<string | null>(null);

  languageRef.current = language;
  onTranscriptRef.current = onTranscript;
  initialGreetingRef.current = initialGreeting;
  onGreetingRef.current = onGreeting;

  useEffect(() => {
    const hasMedia =
      typeof navigator !== 'undefined' &&
      typeof navigator.mediaDevices?.getUserMedia === 'function' &&
      typeof MediaRecorder !== 'undefined' &&
      typeof window !== 'undefined' &&
      typeof window.AudioContext !== 'undefined';
    setSupported(voiceFeatureEnabled && hasMedia);
  }, []);

  const updateState = useCallback((next: VoiceCallState) => {
    stateRef.current = next;
    setState(next);
  }, []);

  const clearVadTimers = useCallback(() => {
    if (vadIntervalRef.current !== null) {
      window.clearInterval(vadIntervalRef.current);
      vadIntervalRef.current = null;
    }
    if (maxDurationTimerRef.current !== null) {
      window.clearTimeout(maxDurationTimerRef.current);
      maxDurationTimerRef.current = null;
    }
    if (noSpeechTimerRef.current !== null) {
      window.clearTimeout(noSpeechTimerRef.current);
      noSpeechTimerRef.current = null;
    }
  }, []);

  const teardownAudioGraph = useCallback(() => {
    try {
      sourceRef.current?.disconnect();
    } catch {
      // ignore
    }
    sourceRef.current = null;
    analyserRef.current = null;
    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      void audioContextRef.current.close().catch(() => undefined);
    }
    audioContextRef.current = null;
  }, []);

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const stopRecorder = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== 'inactive') {
      try {
        recorder.stop();
      } catch {
        // ignore
      }
    }
  }, []);

  const stopPlayback = useCallback(() => {
    const audio = playingAudioRef.current;
    if (audio) {
      try {
        audio.pause();
        audio.src = '';
      } catch {
        // ignore
      }
    }
    playingAudioRef.current = null;
    if (playingAudioUrlRef.current) {
      URL.revokeObjectURL(playingAudioUrlRef.current);
      playingAudioUrlRef.current = null;
    }
  }, []);

  const releaseListeningResources = useCallback(() => {
    clearVadTimers();
    teardownAudioGraph();
    stopStream();
  }, [clearVadTimers, teardownAudioGraph, stopStream]);

  // Forward declaration so listenOnce and handleRecorderStop can reference each other.
  const listenOnceRef = useRef<(() => Promise<void>) | null>(null);

  const handleRecorderStop = useCallback(
    async (gen: number) => {
      clearVadTimers();
      teardownAudioGraph();
      stopStream();

      const recorder = recorderRef.current;
      recorderRef.current = null;

      if (!activeRef.current || gen !== generationRef.current) {
        chunksRef.current = [];
        return;
      }

      const blobType = recorder?.mimeType || 'audio/webm';
      const blob = new Blob(chunksRef.current, { type: blobType });
      chunksRef.current = [];

      if (blob.size === 0) {
        // Nothing captured — try again
        if (activeRef.current && gen === generationRef.current) {
          await listenOnceRef.current?.();
        }
        return;
      }

      updateState('uploading');
      let transcript = '';
      try {
        const result = await api.stt(blob, languageRef.current, fileNameForMime(blobType));
        if (gen !== generationRef.current || !activeRef.current) return;
        transcript = result.transcript?.trim() ?? '';
        setLastTranscript(transcript);
      } catch (err) {
        if (gen !== generationRef.current || !activeRef.current) return;
        setError(err instanceof Error ? err.message : 'Speech recognition failed');
        // Recover: try listening again rather than ending the call
        await listenOnceRef.current?.();
        return;
      }

      if (!transcript) {
        if (activeRef.current && gen === generationRef.current) {
          await listenOnceRef.current?.();
        }
        return;
      }

      updateState('thinking');
      let reply: string | null | undefined;
      try {
        reply = await onTranscriptRef.current(transcript);
      } catch (err) {
        if (gen !== generationRef.current || !activeRef.current) return;
        setError(err instanceof Error ? err.message : 'Chat request failed');
        await listenOnceRef.current?.();
        return;
      }
      if (gen !== generationRef.current || !activeRef.current) return;

      if (!reply || !reply.trim()) {
        if (activeRef.current && gen === generationRef.current) {
          await listenOnceRef.current?.();
        }
        return;
      }

      setLastReply(reply);
      updateState('speaking');
      await speakTextRef.current?.(reply, gen);

      if (activeRef.current && gen === generationRef.current) {
        await listenOnceRef.current?.();
      }
    },
    [clearVadTimers, teardownAudioGraph, stopStream, updateState],
  );

  // Fetch TTS and play audio. Returns when playback finishes (or fails).
  // Pulled out of the recorder-stop pipeline so the greeting can reuse it.
  const speakTextRef = useRef<((text: string, gen: number) => Promise<void>) | null>(null);
  const speakText = useCallback(
    async (text: string, gen: number) => {
      if (!text.trim()) return;
      try {
        const audioBlob = await api.tts(text, languageRef.current);
        if (gen !== generationRef.current || !activeRef.current) return;

        const url = URL.createObjectURL(audioBlob);
        playingAudioUrlRef.current = url;
        const audio = new Audio(url);
        playingAudioRef.current = audio;

        await new Promise<void>((resolve) => {
          let settled = false;
          const finish = () => {
            if (settled) return;
            settled = true;
            resolve();
          };
          audio.onended = finish;
          audio.onerror = finish;
          audio.play().catch(() => finish());
        });

        stopPlayback();
      } catch (err) {
        if (gen !== generationRef.current || !activeRef.current) return;
        setError(err instanceof Error ? err.message : 'Voice playback failed');
      }
    },
    [stopPlayback],
  );
  speakTextRef.current = speakText;

  const listenOnce = useCallback(async () => {
    if (!activeRef.current) return;
    const gen = generationRef.current;

    setError(null);
    updateState('listening');

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Microphone access denied');
      activeRef.current = false;
      updateState('error');
      return;
    }

    if (!activeRef.current || gen !== generationRef.current) {
      stream.getTracks().forEach((track) => track.stop());
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
      if (event.data.size > 0) chunksRef.current.push(event.data);
    };
    recorder.onstop = () => {
      void handleRecorderStop(gen);
    };

    // VAD pipeline
    const AudioCtor =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const audioContext = new AudioCtor();
    audioContextRef.current = audioContext;
    const source = audioContext.createMediaStreamSource(stream);
    sourceRef.current = source;
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0.5;
    source.connect(analyser);
    analyserRef.current = analyser;

    const buffer = new Float32Array(analyser.fftSize);
    const startedAt = performance.now();
    let speechStartedAt: number | null = null;
    let lastSpeechAt: number | null = null;
    let inSpeech = false;
    // Adaptive noise floor — refined during the first NOISE_CALIBRATION_MS of
    // each listen turn, then frozen. Falls back to a sane default so we never
    // get stuck if the mic delivers all-zeros during calibration.
    let noiseFloor = 0.003;
    let noiseSamples = 0;

    recorder.start();

    vadIntervalRef.current = window.setInterval(() => {
      if (!analyserRef.current || !recorderRef.current) return;
      if (recorderRef.current.state !== 'recording') return;
      analyserRef.current.getFloatTimeDomainData(buffer);

      let sumSquares = 0;
      for (let i = 0; i < buffer.length; i++) {
        const v = buffer[i];
        sumSquares += v * v;
      }
      const rms = Math.sqrt(sumSquares / buffer.length);
      const now = performance.now();
      const sinceStart = now - startedAt;

      // Phase 1: ambient noise calibration. We track a running max so we
      // pick up the loudest blip of the background (HVAC, fans, etc) and
      // raise the speech threshold above that. We do NOT trigger speech
      // detection during this short window.
      if (sinceStart < NOISE_CALIBRATION_MS) {
        if (noiseSamples === 0 || rms > noiseFloor) {
          noiseFloor = rms;
        }
        noiseSamples += 1;
        return;
      }

      const speechThreshold = Math.max(SPEECH_RMS_THRESHOLD, noiseFloor * NOISE_MULTIPLIER_SPEECH);
      const silenceThreshold = Math.max(SILENCE_RMS_THRESHOLD, noiseFloor * NOISE_MULTIPLIER_SILENCE);

      // Hysteresis: enter speech only above the high threshold, stay in speech
      // until we drop below the low threshold. Mid-sentence dips (breathing,
      // unvoiced consonants, brief pauses) won't kick us out of speech state.
      if (!inSpeech) {
        if (rms >= speechThreshold) {
          inSpeech = true;
          if (speechStartedAt === null) speechStartedAt = now;
          lastSpeechAt = now;
        }
      } else {
        if (rms >= silenceThreshold) {
          // Still speaking (or in a tiny dip that's still above silence floor)
          lastSpeechAt = now;
        } else {
          // Dropped into silence — leave speech state but DO NOT update
          // lastSpeechAt, so the hangover timer starts counting from now.
          inSpeech = false;
        }
      }

      if (speechStartedAt !== null && lastSpeechAt !== null) {
        const utteranceMs = now - speechStartedAt;
        const silenceMs = inSpeech ? 0 : now - lastSpeechAt;
        if (utteranceMs >= MIN_UTTERANCE_MS && silenceMs >= SILENCE_HANGOVER_MS) {
          stopRecorder();
        }
      } else if (sinceStart >= NO_SPEECH_TIMEOUT_MS) {
        // Long silence with no speech ever detected — restart the cycle so we
        // pick up a fresh mic stream + fresh noise floor.
        stopRecorder();
      }
    }, VAD_SAMPLE_INTERVAL_MS);

    maxDurationTimerRef.current = window.setTimeout(() => {
      stopRecorder();
    }, MAX_UTTERANCE_MS);
  }, [handleRecorderStop, stopRecorder, updateState]);

  listenOnceRef.current = listenOnce;

  const start = useCallback(async () => {
    if (!supported) {
      setError('Voice calling is not supported in this browser.');
      return;
    }
    if (activeRef.current) return;
    activeRef.current = true;
    generationRef.current += 1;
    const gen = generationRef.current;
    setError(null);
    setLastTranscript('');
    setLastReply('');
    updateState('starting');

    const greeting = initialGreetingRef.current?.trim();
    if (greeting) {
      setLastReply(greeting);
      // Fire-and-forget side effect for the caller (e.g. persist the greeting
      // as an assistant message so it shows up in chat history later).
      if (onGreetingRef.current) {
        try {
          await Promise.resolve(onGreetingRef.current(greeting));
        } catch {
          // ignore — the greeting itself must still play
        }
      }
      if (!activeRef.current || gen !== generationRef.current) return;
      updateState('greeting');
      await speakText(greeting, gen);
      if (!activeRef.current || gen !== generationRef.current) return;
    }

    await listenOnce();
  }, [supported, listenOnce, speakText, updateState]);

  const end = useCallback(() => {
    activeRef.current = false;
    generationRef.current += 1;
    stopRecorder();
    stopPlayback();
    releaseListeningResources();
    chunksRef.current = [];
    updateState('idle');
  }, [stopRecorder, stopPlayback, releaseListeningResources, updateState]);

  useEffect(() => {
    return () => {
      activeRef.current = false;
      generationRef.current += 1;
      stopRecorder();
      stopPlayback();
      releaseListeningResources();
    };
  }, [stopRecorder, stopPlayback, releaseListeningResources]);

  return {
    state,
    active: state !== 'idle' && state !== 'error',
    supported,
    error,
    lastTranscript,
    lastReply,
    start,
    end,
  };
}
