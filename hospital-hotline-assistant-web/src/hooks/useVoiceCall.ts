import { useCallback, useEffect, useRef, useState } from 'react';
import { baseUrl } from '../api/client';
import type { ChatResponsePayload } from '../api/types';
import type { AppLanguage } from '../i18n/resources';
import { takePrewarmedPlaybackContext } from './voicePrewarm';

/**
 * Continuous voice-call hook backed by the backend's
 * `WS /ws/voice/{session_id}` Gemini Live API bridge.
 *
 * Flow:
 *   1. ``start()`` opens the WebSocket, requests the mic, and pipes raw PCM
 *      16-bit / 16 kHz / mono frames over the socket as binary messages.
 *   2. Server pushes back raw PCM 24 kHz mono frames; we schedule them on a
 *      24 kHz AudioContext so consecutive chunks play gap-free.
 *   3. Mute is a client-side gate that ALSO sends a JSON control message so
 *      the server suppresses its own queue. The socket stays open.
 *   4. ``end()`` sends ``{"type":"end_call"}`` and waits briefly for the
 *      server's ``call_ended`` ack, then tears down everything.
 *
 * State names are kept compatible with the previous REST-based hook so
 * existing CallPage i18n keys (``callStateListening``,
 * ``callStateSpeaking`` etc) still resolve.
 */

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
  /** Hotline session ID returned from ``POST /sessions``. */
  sessionId: string | null;
  language: AppLanguage;
  /**
   * Legacy callback from the REST pipeline. Unused in live mode but kept
   * in the signature so the CallPage prop bag stays backward-compatible.
   */
  onTranscript?: (transcript: string) => Promise<string | null | undefined>;
  /** Fired when the backend finalizes triage and pushes assessment_complete. */
  onAssessmentComplete?: (payload: ChatResponsePayload) => void;
}

export interface VoiceEmergencyPayload {
  severity?: string;
  level?: number;
  alertMessage?: string;
  departmentCode?: string;
  color?: string;
  label?: string;
  detectedSymptoms?: string[];
}

export interface UseVoiceCallApi {
  state: VoiceCallState;
  active: boolean;
  supported: boolean;
  muted: boolean;
  /** True when the assistant's audio response is played through the
   *  speakers. When false, incoming PCM frames are dropped silently
   *  so the call continues but the caller hears nothing. The transcript
   *  caption keeps updating either way so the user can still read the
   *  reply. */
  speakerEnabled: boolean;
  error: string | null;
  lastTranscript: string;
  lastReply: string;
  emergency: VoiceEmergencyPayload | null;
  /** Set when the server sends ``assessment_complete`` (triage finished). */
  completedAssessment: ChatResponsePayload | null;
  /** True while waiting for the agent to finish speaking before auto-hangup. */
  autoEnding: boolean;
  start: () => Promise<void>;
  end: () => Promise<void>;
  sendTurn: () => void;
  toggleMute: () => void;
  setMuted: (muted: boolean) => void;
  toggleSpeaker: () => void;
  setSpeakerEnabled: (enabled: boolean) => void;
}

const voiceFeatureEnabled = import.meta.env.VITE_ENABLE_VOICE === 'true';
// Set ``VITE_VOICE_DEBUG=true`` in ``.env.local`` (or any Vite-loaded
// env) to log first-chunk-in / first-chunk-out + AudioContext state
// to the browser console. Cheap (a handful of one-off log lines per
// call) and the single source of truth for verifying that PCM is
// actually flowing in both directions.
const voiceDebugEnabled = import.meta.env.VITE_VOICE_DEBUG === 'true';

// PCM rates: Gemini Live wants 16 kHz mono input, sends 24 kHz mono output.
const INPUT_SAMPLE_RATE = 16000;
const OUTPUT_SAMPLE_RATE = 24000;

// How long after the last server-sent audio chunk before we flip the UI
// back from "speaking" to "listening". Gemini Live tends to send tightly
// packed bursts followed by gaps; a small grace period prevents the orb
// from flickering between states mid-utterance.
const SPEAKING_IDLE_GRACE_MS = 250;

// How long to wait for the server's ``call_ended`` ack after we send
// ``end_call`` before we tear down anyway. Real network jitter rarely
// exceeds a second; a 1500 ms ceiling is generous without feeling slow.
const END_CALL_ACK_TIMEOUT_MS = 1500;
// After assessment_complete, wait this long once playback is idle before
// hanging up so the patient hears the full spoken summary.
const AUTO_END_AFTER_ASSESSMENT_MS = 2500;

/**
 * AudioWorklet processor source. We ship it inline (as a blob URL) so the
 * frontend stays a single bundle — no separate static file to misplace.
 *
 * Per-frame the browser feeds us Float32 samples at the AudioContext's
 * native sample rate (typically 44.1 kHz or 48 kHz). We linearly
 * interpolate down to 16 kHz, convert to little-endian Int16, and emit
 * ~40 ms chunks (640 samples) so the WS sees a steady stream of small
 * frames rather than bursts.
 */
const PCM_WORKLET_SOURCE = String.raw`
class PcmDownsampleProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const opts = (options && options.processorOptions) || {};
    this._outputRate = opts.outputRate || 16000;
    this._ratio = sampleRate / this._outputRate;
    this._chunkSamples = Math.max(160, Math.floor(this._outputRate * 0.04));
    this._buffer = new Int16Array(this._chunkSamples);
    this._writeIdx = 0;
    this._readCursor = 0;
  }
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel || channel.length === 0) return true;
    // Linear-interpolated resampling. _readCursor tracks our fractional
    // position into the input buffer so that successive process() calls
    // pick up exactly where the previous one left off (otherwise we'd
    // get aliasing artifacts at frame boundaries).
    while (this._readCursor < channel.length) {
      const idx = Math.floor(this._readCursor);
      const frac = this._readCursor - idx;
      const a = channel[idx];
      const b = idx + 1 < channel.length ? channel[idx + 1] : a;
      const sample = a * (1 - frac) + b * frac;
      const clipped = Math.max(-1, Math.min(1, sample));
      this._buffer[this._writeIdx++] = clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff;
      if (this._writeIdx >= this._chunkSamples) {
        // Transfer the ArrayBuffer ownership across threads for zero-copy.
        this.port.postMessage(this._buffer.buffer, [this._buffer.buffer]);
        this._buffer = new Int16Array(this._chunkSamples);
        this._writeIdx = 0;
      }
      this._readCursor += this._ratio;
    }
    this._readCursor -= channel.length;
    return true;
  }
}
registerProcessor('pcm-downsample', PcmDownsampleProcessor);
`;

function buildWebSocketUrl(sessionId: string, language: string): string {
  const wsBase = baseUrl.replace(/^http/, 'ws');
  const normalizedLanguage = language === 'th' ? 'th' : 'en';
  return `${wsBase}/ws/voice/${encodeURIComponent(sessionId)}?language=${encodeURIComponent(normalizedLanguage)}`;
}

/**
 * Merge an incoming Gemini Live transcript fragment with the current
 * caption buffer in a way that's robust to the API's interim/final/
 * snapshot behaviour.
 *
 * Even with the backend's ``_smart_append`` dedupe in place, the frontend
 * stays defensive: if Gemini Live re-emits the same final phrase, the
 * caption shouldn't grow to ``X X``. Mirrors the server-side logic:
 *
 *   - empty fragment → buffer unchanged
 *   - buffer ends with fragment → already shown, ignore
 *   - fragment starts with buffer → cumulative snapshot, replace
 *   - otherwise → true delta, append
 */
function smartMergeTranscript(buffer: string, fragment: string): string {
  let f = fragment.trim();
  if (!f) return buffer;
  const words = f.split(/\s+/);
  if (words.length > 1 && words.length % 2 === 0) {
    const midpoint = words.length / 2;
    const first = words.slice(0, midpoint);
    const second = words.slice(midpoint);
    if (first.every((word, index) => word === second[index])) {
      f = first.join(' ');
    }
  }
  const b = buffer.trim();
  if (!b) return f;
  if (b.endsWith(f)) return b;
  if (f.startsWith(b)) return f;
  return `${b} ${f}`;
}

function makeWorkletBlobUrl(): string {
  const blob = new Blob([PCM_WORKLET_SOURCE], { type: 'application/javascript' });
  return URL.createObjectURL(blob);
}

/**
 * Convert a server-sent Int16 PCM chunk into an AudioBuffer at the
 * playback context's native sample rate.
 */
function pcm16ToAudioBuffer(
  ctx: AudioContext,
  data: ArrayBuffer,
): AudioBuffer {
  const int16 = new Int16Array(data);
  const buffer = ctx.createBuffer(1, int16.length, OUTPUT_SAMPLE_RATE);
  const channel = buffer.getChannelData(0);
  for (let i = 0; i < int16.length; i++) {
    channel[i] = int16[i] / 0x8000;
  }
  return buffer;
}

interface PlaybackQueueRef {
  ctx: AudioContext;
  nextStartTime: number;
  scheduledCount: number;
  onIdle: () => void;
}

export function useVoiceCall(options: UseVoiceCallOptions): UseVoiceCallApi {
  const { sessionId, language, onAssessmentComplete } = options;

  const [state, setState] = useState<VoiceCallState>('idle');
  const [muted, setMutedState] = useState(false);
  const [speakerEnabled, setSpeakerEnabledState] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastTranscript, setLastTranscript] = useState('');
  const [lastReply, setLastReply] = useState('');
  const [emergency, setEmergency] = useState<VoiceEmergencyPayload | null>(null);
  const [completedAssessment, setCompletedAssessment] =
    useState<ChatResponsePayload | null>(null);
  const [autoEnding, setAutoEnding] = useState(false);
  const [supported, setSupported] = useState(false);

  // Server sends transcripts as short incremental fragments. We accumulate
  // them per role within a single utterance so the caption shows the
  // whole sentence rather than just the most recent token. The cutover
  // between utterances is detected by switching roles or a sufficiently
  // long pause — for the demo, a simple role-based reset works.
  const transcriptAccumRef = useRef<{ user: string; agent: string }>({
    user: '',
    agent: '',
  });

  // Refs hold all I/O resources so callbacks always see the latest
  // values without having to rebuild on every render.
  const stateRef = useRef<VoiceCallState>('idle');
  const mutedRef = useRef(false);
  const speakerEnabledRef = useRef(true);
  const activeRef = useRef(false);
  const languageRef = useRef(language);
  const sessionIdRef = useRef(sessionId);
  const onAssessmentCompleteRef = useRef(onAssessmentComplete);
  const pendingAutoEndRef = useRef(false);
  const autoEndTimerRef = useRef<number | null>(null);
  const endRef = useRef<(() => Promise<void>) | null>(null);

  languageRef.current = language;
  sessionIdRef.current = sessionId;
  onAssessmentCompleteRef.current = onAssessmentComplete;

  const wsRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const inputCtxRef = useRef<AudioContext | null>(null);
  const inputNodeRef = useRef<AudioWorkletNode | null>(null);
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const workletUrlRef = useRef<string | null>(null);
  const playbackRef = useRef<PlaybackQueueRef | null>(null);
  const speakingTimerRef = useRef<number | null>(null);
  const endCallAckRef = useRef<{ resolve: () => void; timer: number } | null>(null);
  // Per-call counters used only when ``voiceDebugEnabled`` is true.
  // Reset on every ``start()`` so each call's audit is independent.
  const debugRef = useRef({
    inputChunks: 0,
    inputBytes: 0,
    outputChunks: 0,
    outputBytes: 0,
    firstInputLogged: false,
    firstOutputLogged: false,
  });

  useEffect(() => {
    const hasMedia =
      typeof navigator !== 'undefined' &&
      typeof navigator.mediaDevices?.getUserMedia === 'function' &&
      typeof window !== 'undefined' &&
      typeof window.AudioContext !== 'undefined' &&
      typeof window.WebSocket !== 'undefined';
    setSupported(voiceFeatureEnabled && hasMedia);
  }, []);

  const updateState = useCallback((next: VoiceCallState) => {
    stateRef.current = next;
    setState(next);
  }, []);

  const tryScheduleAutoEnd = useCallback(() => {
    if (!pendingAutoEndRef.current || !activeRef.current) return;
    if (autoEndTimerRef.current !== null) return;

    autoEndTimerRef.current = window.setTimeout(() => {
      autoEndTimerRef.current = null;
      if (!pendingAutoEndRef.current || !activeRef.current) return;
      pendingAutoEndRef.current = false;
      setAutoEnding(false);
      void endRef.current?.();
    }, AUTO_END_AFTER_ASSESSMENT_MS);
  }, []);

  // ----- Playback (server → speakers) ----------------------------------

  const ensurePlaybackContext = useCallback((): PlaybackQueueRef => {
    if (playbackRef.current) {
      // Defensive: if the playback context was ``suspend()``-ed by the
      // browser (autoplay policy, tab visibility, ``visibilityState``
      // background, OS audio focus shift) between the time we created
      // it and the next chunk's arrival, scheduled BufferSources will
      // silently produce no sound. Resume on every chunk so the queue
      // stays audible regardless of background state churn.
      if (playbackRef.current.ctx.state === 'suspended') {
        void playbackRef.current.ctx.resume().catch(() => undefined);
      }
      return playbackRef.current;
    }
    // Prefer a context the landing page already constructed inside a
    // user-gesture handler — this avoids any autoplay-policy edge cases
    // and saves the ~50-100 ms it takes the audio thread to spin one up
    // on first use. Falls back to a fresh context if no prewarm
    // happened (e.g. user landed directly on /call via a deep link).
    const prewarmed = takePrewarmedPlaybackContext();
    let ctx: AudioContext;
    if (prewarmed) {
      ctx = prewarmed;
    } else {
      const Ctor =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext })
          .webkitAudioContext;
      // Pinning sampleRate to 24 kHz matches Gemini Live's output and
      // avoids the browser doing an extra resample pass on every chunk.
      ctx = new Ctor({ sampleRate: OUTPUT_SAMPLE_RATE });
    }
    // Brand-new contexts can also start in ``suspended`` even when
    // constructed inside a gesture (e.g. iOS Safari). ``resume()`` is
    // a no-op if already running, so always-call is safe.
    if (ctx.state === 'suspended') {
      void ctx.resume().catch(() => undefined);
    }
    const queue: PlaybackQueueRef = {
      ctx,
      nextStartTime: 0,
      scheduledCount: 0,
      onIdle: () => {
        // Flip back to "listening" once the agent's audio queue drains,
        // with a small grace period so we don't flicker between chunks.
        if (speakingTimerRef.current !== null) {
          window.clearTimeout(speakingTimerRef.current);
        }
        speakingTimerRef.current = window.setTimeout(() => {
          if (activeRef.current && stateRef.current === 'speaking') {
            updateState('listening');
          }
          if (
            activeRef.current &&
            mutedRef.current &&
            !pendingAutoEndRef.current
          ) {
            mutedRef.current = false;
            setMutedState(false);
            const ws = wsRef.current;
            if (ws && ws.readyState === WebSocket.OPEN) {
              try {
                ws.send(JSON.stringify({ type: 'unmute' }));
              } catch {
                // The next explicit mute/unmute action will resync state.
              }
            }
          }
          speakingTimerRef.current = null;
          if (pendingAutoEndRef.current) {
            tryScheduleAutoEnd();
          }
        }, SPEAKING_IDLE_GRACE_MS);
      },
    };
    playbackRef.current = queue;
    return queue;
  }, [updateState, tryScheduleAutoEnd]);

  const schedulePlaybackChunk = useCallback(
    (data: ArrayBuffer) => {
      if (!activeRef.current) return;
      // Speaker off: drop the chunk on the floor. The transcript
      // caption pathway is on a different channel (JSON over the
      // same WS) so the user still sees the agent's words even
      // though they hear nothing.
      if (!speakerEnabledRef.current) return;
      // Bail on odd-sized chunks before they tank Int16Array
      // construction. Gemini Live should never send these (output is
      // documented PCM 24 kHz mono Int16 = always even bytes) but the
      // empty / partial frame case has shown up on disconnect races.
      if (data.byteLength === 0 || data.byteLength % 2 !== 0) {
        if (voiceDebugEnabled) {
          // eslint-disable-next-line no-console
          console.warn(
            `[voice-audit] server → client: dropping odd-sized chunk ${data.byteLength} bytes`,
          );
        }
        return;
      }
      if (pendingAutoEndRef.current && autoEndTimerRef.current !== null) {
        window.clearTimeout(autoEndTimerRef.current);
        autoEndTimerRef.current = null;
      }
      const queue = ensurePlaybackContext();
      let buffer: AudioBuffer;
      try {
        buffer = pcm16ToAudioBuffer(queue.ctx, data);
      } catch (err) {
        if (voiceDebugEnabled) {
          // eslint-disable-next-line no-console
          console.warn(
            `[voice-audit] server → client: pcm conversion failed (${data.byteLength} bytes):`,
            err,
          );
        }
        return;
      }
      const startAt = Math.max(queue.ctx.currentTime + 0.02, queue.nextStartTime);
      const src = queue.ctx.createBufferSource();
      src.buffer = buffer;
      src.connect(queue.ctx.destination);
      src.start(startAt);
      queue.nextStartTime = startAt + buffer.duration;
      queue.scheduledCount += 1;
      src.onended = () => {
        queue.scheduledCount = Math.max(0, queue.scheduledCount - 1);
        if (queue.scheduledCount === 0) queue.onIdle();
      };
      if (stateRef.current !== 'speaking') updateState('speaking');

      if (voiceDebugEnabled) {
        const dbg = debugRef.current;
        dbg.outputChunks += 1;
        dbg.outputBytes += data.byteLength;
        if (!dbg.firstOutputLogged) {
          dbg.firstOutputLogged = true;
          // First output chunk's byte count + AudioContext state
          // tell us whether the playback graph is actually live.
          // Anything where ``ctx.state !== 'running'`` means audio
          // is being scheduled into a suspended graph — the chunks
          // arrive but the user hears nothing.
          // eslint-disable-next-line no-console
          console.info(
            `[voice-audit] server → client: first chunk ${data.byteLength} bytes ` +
              `(${buffer.duration.toFixed(3)}s @ ${queue.ctx.sampleRate} Hz), ` +
              `ctx.state=${queue.ctx.state}`,
          );
        }
        if (dbg.outputChunks % 50 === 0) {
          // eslint-disable-next-line no-console
          console.info(
            `[voice-audit] server → client: ${dbg.outputChunks} chunks, ${dbg.outputBytes} bytes, ctx.state=${queue.ctx.state}`,
          );
        }
      }
    },
    [ensurePlaybackContext, updateState],
  );

  const teardownPlayback = useCallback(() => {
    const queue = playbackRef.current;
    if (!queue) return;
    try {
      if (queue.ctx.state !== 'closed') void queue.ctx.close().catch(() => undefined);
    } catch {
      // ignore
    }
    playbackRef.current = null;
    if (speakingTimerRef.current !== null) {
      window.clearTimeout(speakingTimerRef.current);
      speakingTimerRef.current = null;
    }
  }, []);

  // ----- Mic capture (browser → server) --------------------------------

  const teardownInputGraph = useCallback(() => {
    try {
      inputNodeRef.current?.port.close();
      inputNodeRef.current?.disconnect();
    } catch {
      // ignore
    }
    inputNodeRef.current = null;
    try {
      sourceNodeRef.current?.disconnect();
    } catch {
      // ignore
    }
    sourceNodeRef.current = null;
    if (inputCtxRef.current && inputCtxRef.current.state !== 'closed') {
      void inputCtxRef.current.close().catch(() => undefined);
    }
    inputCtxRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (workletUrlRef.current) {
      URL.revokeObjectURL(workletUrlRef.current);
      workletUrlRef.current = null;
    }
  }, []);

  const startMicPipeline = useCallback(async (): Promise<void> => {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      },
    });
    streamRef.current = stream;

    const Ctor =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext })
        .webkitAudioContext;
    const ctx = new Ctor();
    inputCtxRef.current = ctx;

    const workletUrl = makeWorkletBlobUrl();
    workletUrlRef.current = workletUrl;
    await ctx.audioWorklet.addModule(workletUrl);

    const source = ctx.createMediaStreamSource(stream);
    sourceNodeRef.current = source;
    const node = new AudioWorkletNode(ctx, 'pcm-downsample', {
      processorOptions: { outputRate: INPUT_SAMPLE_RATE },
    });
    inputNodeRef.current = node;

    node.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
      if (!activeRef.current || mutedRef.current) return;
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      ws.send(event.data);
      if (voiceDebugEnabled) {
        const dbg = debugRef.current;
        dbg.inputChunks += 1;
        dbg.inputBytes += event.data.byteLength;
        if (!dbg.firstInputLogged) {
          dbg.firstInputLogged = true;
          // First chunk shape — should be 1280 bytes = 640 Int16 PCM
          // samples = 40ms at 16kHz mono. Anything materially different
          // means the worklet downsampler is misconfigured (wrong
          // ratio, wrong chunk size, wrong byte order).
          // eslint-disable-next-line no-console
          console.info(
            `[voice-audit] input → server: first chunk ${event.data.byteLength} bytes ` +
              `(expected 1280 for 40ms 16kHz mono Int16); ctx.sampleRate=${
                inputCtxRef.current?.sampleRate ?? '?'
              } Hz, target=${INPUT_SAMPLE_RATE} Hz`,
          );
        }
        if (dbg.inputChunks % 50 === 0) {
          // Roughly every 2 s of speech at 40ms/chunk.
          // eslint-disable-next-line no-console
          console.info(
            `[voice-audit] input → server: ${dbg.inputChunks} chunks, ${dbg.inputBytes} bytes total`,
          );
        }
      }
    };

    source.connect(node);
    // The worklet doesn't need to route to destination — we only care
    // about pulling frames into the WS. Connecting to a dummy GainNode
    // at gain=0 keeps the graph alive without echoing the mic locally.
    const sink = ctx.createGain();
    sink.gain.value = 0;
    node.connect(sink).connect(ctx.destination);
  }, []);

  // ----- WebSocket message handling ------------------------------------

  const handleWsMessage = useCallback(
    (event: MessageEvent) => {
      if (typeof event.data === 'string') {
        let payload: unknown;
        try {
          payload = JSON.parse(event.data);
        } catch {
          return;
        }
        if (!payload || typeof payload !== 'object') return;
        const message = payload as {
          type?: string;
          muted?: boolean;
          message?: string;
          role?: string;
          text?: string;
          severity?: string;
          level?: number;
          alert_message?: string;
          department_code?: string;
          color?: string;
          label?: string;
          detected_symptoms?: string[];
        };
        switch (message.type) {
          case 'status':
            if (typeof message.muted === 'boolean') {
              mutedRef.current = message.muted;
              setMutedState(message.muted);
            }
            return;
          case 'call_ended':
            if (endCallAckRef.current) {
              window.clearTimeout(endCallAckRef.current.timer);
              endCallAckRef.current.resolve();
              endCallAckRef.current = null;
            }
            return;
          case 'error':
            setError(message.message ?? 'Voice service error');
            return;
          case 'transcript': {
            const role = message.role === 'agent' ? 'agent' : 'user';
            const text = (message.text ?? '').toString();
            if (!text) return;
            // Accumulate within the current utterance, reset the other
            // role's buffer so we don't bleed an old fragment forward.
            // ``smartMergeTranscript`` keeps captions clean even when the
            // server (or Gemini Live) re-emits the same finalised phrase.
            const accum = transcriptAccumRef.current;
            if (role === 'user') {
              accum.user = smartMergeTranscript(accum.user, text);
              setLastTranscript(accum.user);
              accum.agent = '';
            } else {
              accum.agent = smartMergeTranscript(accum.agent, text);
              setLastReply(accum.agent);
              accum.user = '';
            }
            return;
          }
          case 'emergency': {
            setEmergency({
              severity: message.severity,
              level: message.level,
              alertMessage: message.alert_message,
              departmentCode: message.department_code,
              color: message.color,
              label: message.label,
              detectedSymptoms: message.detected_symptoms,
            });
            return;
          }
          case 'assessment_complete': {
            const payload = message as unknown as ChatResponsePayload & {
              type?: string;
              auto_end?: boolean;
            };
            const assessmentPayload: ChatResponsePayload = {
              reply: payload.reply ?? '',
              severity: payload.severity ?? { level: 'unknown' },
              department: payload.department ?? null,
              emergency: payload.emergency ?? null,
              symptoms: payload.symptoms ?? null,
              follow_up_question: payload.follow_up_question ?? null,
              follow_up_reason: payload.follow_up_reason ?? null,
              model_name: payload.model_name ?? null,
              latency_ms: payload.latency_ms ?? null,
              alert_sent: payload.alert_sent ?? false,
              assistant_message_id: payload.assistant_message_id ?? null,
            };
            setCompletedAssessment(assessmentPayload);
            if (assessmentPayload.reply) {
              setLastReply(assessmentPayload.reply);
            }
            try {
              onAssessmentCompleteRef.current?.(assessmentPayload);
            } catch {
              // best-effort
            }
            if (payload.auto_end !== false) {
              pendingAutoEndRef.current = true;
              setAutoEnding(true);
              // If the speaker is off or no audio is queued, onIdle may
              // never fire — schedule auto-end directly as a fallback.
              const queue = playbackRef.current;
              if (
                !speakerEnabledRef.current ||
                !queue ||
                queue.scheduledCount === 0
              ) {
                tryScheduleAutoEnd();
              }
            }
            return;
          }
          default:
            return;
        }
      }

      // Binary path: ArrayBuffer or Blob depending on browser config.
      const data = event.data as ArrayBuffer | Blob;
      if (data instanceof ArrayBuffer) {
        schedulePlaybackChunk(data);
      } else if (data instanceof Blob) {
        void data.arrayBuffer().then((buf) => schedulePlaybackChunk(buf));
      }
    },
    [schedulePlaybackChunk, tryScheduleAutoEnd],
  );

  // ----- Lifecycle: start / end ----------------------------------------

  const cleanup = useCallback(() => {
    activeRef.current = false;
    pendingAutoEndRef.current = false;
    setAutoEnding(false);
    if (autoEndTimerRef.current !== null) {
      window.clearTimeout(autoEndTimerRef.current);
      autoEndTimerRef.current = null;
    }
    if (endCallAckRef.current) {
      window.clearTimeout(endCallAckRef.current.timer);
      endCallAckRef.current.resolve();
      endCallAckRef.current = null;
    }
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws) {
      try {
        ws.onmessage = null;
        ws.onclose = null;
        ws.onerror = null;
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
          ws.close();
        }
      } catch {
        // ignore
      }
    }
    teardownInputGraph();
    teardownPlayback();
    mutedRef.current = false;
    setMutedState(false);
  }, [teardownInputGraph, teardownPlayback]);

  const start = useCallback(async () => {
    if (!supported) {
      setError('Voice calling is not supported in this browser.');
      updateState('error');
      return;
    }
    if (activeRef.current) return;

    activeRef.current = true;
    setError(null);
    setLastTranscript('');
    setLastReply('');
    setEmergency(null);
    setCompletedAssessment(null);
    setAutoEnding(false);
    pendingAutoEndRef.current = false;
    if (autoEndTimerRef.current !== null) {
      window.clearTimeout(autoEndTimerRef.current);
      autoEndTimerRef.current = null;
    }
    transcriptAccumRef.current = { user: '', agent: '' };
    debugRef.current = {
      inputChunks: 0,
      inputBytes: 0,
      outputChunks: 0,
      outputBytes: 0,
      firstInputLogged: false,
      firstOutputLogged: false,
    };
    updateState('starting');

    const activeSessionId = sessionIdRef.current;
    if (!activeSessionId) {
      setError('No active session');
      activeRef.current = false;
      updateState('error');
      return;
    }

    // ---- Parallel setup: WS handshake + mic pipeline ----
    //
    // The WS open and the mic worklet setup are completely independent
    // — the worklet doesn't try to send into the socket until it has
    // received audio AND `activeRef.current` is true (gated below).
    // Awaiting them sequentially used to cost the sum of both delays
    // (~50-200 ms WS handshake + ~50-2000 ms mic permission); doing
    // them concurrently means the visible startup time is the longer
    // of the two instead of their sum.
    let ws: WebSocket;
    try {
      ws = new WebSocket(buildWebSocketUrl(activeSessionId, languageRef.current));
      ws.binaryType = 'arraybuffer';
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to open voice channel');
      activeRef.current = false;
      updateState('error');
      return;
    }
    wsRef.current = ws;

    const openPromise = new Promise<void>((resolve, reject) => {
      const onOpen = () => {
        ws.removeEventListener('open', onOpen);
        ws.removeEventListener('error', onErr);
        resolve();
      };
      const onErr = () => {
        ws.removeEventListener('open', onOpen);
        ws.removeEventListener('error', onErr);
        reject(new Error('WebSocket connection failed'));
      };
      ws.addEventListener('open', onOpen);
      ws.addEventListener('error', onErr);
    });

    // We attach message/close/error handlers BEFORE awaiting so that
    // any frames or close events that race in during the handshake
    // window aren't dropped. (Older code only wired these after the
    // open promise resolved, which left a small gap where Chrome
    // could deliver an early "open + bytes" pair into the void.)
    ws.onmessage = handleWsMessage;
    ws.onclose = () => {
      if (!activeRef.current) return;
      cleanup();
      updateState('idle');
    };
    ws.onerror = () => {
      if (!activeRef.current) return;
      setError('Voice connection lost');
    };

    const micPromise = startMicPipeline();

    // ``Promise.allSettled`` lets us surface the most informative
    // failure mode: if the WS dies we want "Voice connection failed",
    // if the mic is denied we want "Microphone access denied". Plain
    // ``Promise.all`` would let whichever rejected first mask the
    // other, so we inspect each result explicitly.
    const [wsResult, micResult] = await Promise.allSettled([
      openPromise,
      micPromise,
    ]);

    if (wsResult.status === 'rejected') {
      const reason = wsResult.reason;
      setError(reason instanceof Error ? reason.message : 'Voice connection failed');
      cleanup();
      updateState('error');
      return;
    }
    if (micResult.status === 'rejected') {
      const reason = micResult.reason;
      setError(reason instanceof Error ? reason.message : 'Microphone access denied');
      cleanup();
      updateState('error');
      return;
    }

    updateState('listening');
  }, [supported, updateState, handleWsMessage, startMicPipeline, cleanup]);

  const end = useCallback(async () => {
    if (!activeRef.current) {
      cleanup();
      updateState('idle');
      return;
    }
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: 'end_call' }));
      } catch {
        // ignore — we'll fall through to forced cleanup
      }
      // Wait briefly for the server's call_ended ack so the backend can
      // flush the final transcript through process_chat (which is the
      // path that fires MockNotificationService). If the ack doesn't
      // come, tear down anyway — the server still owns its own
      // cleanup via the WebSocketDisconnect handler.
      await new Promise<void>((resolve) => {
        const timer = window.setTimeout(() => {
          if (endCallAckRef.current) {
            endCallAckRef.current = null;
            resolve();
          }
        }, END_CALL_ACK_TIMEOUT_MS);
        endCallAckRef.current = { resolve, timer };
      });
    }
    cleanup();
    updateState('idle');
  }, [cleanup, updateState]);

  endRef.current = end;

  // ----- Turn boundary -------------------------------------------------

  const sendTurn = useCallback(() => {
    if (!activeRef.current || mutedRef.current) return;
    mutedRef.current = true;
    setMutedState(true);
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    try {
      ws.send(JSON.stringify({ type: 'end_of_turn' }));
      updateState('thinking');
    } catch {
      // Keep the local gate closed if the socket is unhealthy.
    }
  }, [updateState]);

  // ----- Mute toggle ---------------------------------------------------

  const setMuted = useCallback(
    (next: boolean) => {
      mutedRef.current = next;
      setMutedState(next);
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      try {
        ws.send(JSON.stringify({ type: next ? 'mute' : 'unmute' }));
        if (!activeRef.current) return;
        if (next) {
          updateState('listening');
        } else if (stateRef.current !== 'speaking') {
          updateState('listening');
        }
      } catch {
        // ignore — UI state is already updated optimistically; server
        // ack will overwrite if it disagrees.
      }
    },
    [updateState],
  );

  const toggleMute = useCallback(() => {
    setMuted(!mutedRef.current);
  }, [setMuted]);

  // ----- Speaker toggle ------------------------------------------------
  //
  // The speaker control is purely client-side — we never tell the
  // backend to stop generating audio, because we still want the
  // transcript to keep flowing on the side channel. We just drop
  // inbound PCM in ``schedulePlaybackChunk`` when disabled. If a
  // user turns the speaker off mid-utterance we also flush the
  // already-scheduled tail by tearing down the playback graph;
  // otherwise the residual buffered chunks would keep playing for
  // up to a few hundred ms after the click.
  const setSpeakerEnabled = useCallback(
    (next: boolean) => {
      speakerEnabledRef.current = next;
      setSpeakerEnabledState(next);
      if (!next) {
        teardownPlayback();
        if (stateRef.current === 'speaking') {
          updateState('listening');
        }
      }
    },
    [teardownPlayback, updateState],
  );

  const toggleSpeaker = useCallback(() => {
    setSpeakerEnabled(!speakerEnabledRef.current);
  }, [setSpeakerEnabled]);

  // ----- Cleanup on unmount --------------------------------------------

  useEffect(() => {
    return () => {
      cleanup();
    };
  }, [cleanup]);

  return {
    state,
    active: state !== 'idle' && state !== 'error',
    supported,
    muted,
    speakerEnabled,
    error,
    lastTranscript,
    lastReply,
    emergency,
    completedAssessment,
    autoEnding,
    start,
    end,
    sendTurn,
    toggleMute,
    setMuted,
    toggleSpeaker,
    setSpeakerEnabled,
  };
}
