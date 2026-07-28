import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { WeightScaleFetchResponse } from '../api/types';

export type ScaleWatchStatus = 'idle' | 'watching' | 'error';
export type ScaleWatchStage = 'step-on' | 'reading';

/** How long the "step on the scale now" prompt stays before switching copy. */
const STEP_ON_MS = 5_000;
/** Give up on auto-detection after this long and show a retry screen.
 *  The HBF-222T daemon needs ~1–2 min from step-on to synced files, so the
 *  default covers step-on + one full sync; callers doing a background
 *  prefetch (the kiosk weigh-in step) pass a longer deadline. */
const WATCH_DEADLINE_MS = 3 * 60_000;
/** Server-side long-poll window per watch call. */
const WATCH_CALL_TIMEOUT_S = 25;
/** Pause between calls only after unexpected statuses/network errors. */
const WATCH_RETRY_DELAY_MS = 1_000;
/** Tolerated scale-vs-kiosk clock drift when judging reading freshness. */
const CLOCK_SKEW_MS = 90_000;

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export interface StartWatchingOptions {
  /** Retry after an error without resetting the freshness anchor. */
  resume?: boolean;
  /** Override the give-up deadline (ms). */
  deadlineMs?: number;
}

export interface UseScaleWatchResult {
  status: ScaleWatchStatus;
  stage: ScaleWatchStage;
  reading: WeightScaleFetchResponse | null;
  /** Set only when ``status === 'error'``; an i18n key for the message. */
  errorKey: string | null;
  /**
   * Hands-free measurement flow: prompt the patient to step on the scale,
   * then long-poll the backend, which resolves the moment the scale syncs
   * a measurement with a sequence above the arm-time baseline (via the
   * omscale daemon's published files or a direct BLE fetch, depending on
   * the API's SCALE_READ_MODE). Novelty is judged by the scale's sequence
   * counter server-side — immune to scale-clock resets; the freshness
   * anchor only guards the initial "did they already step on?" fetch.
   */
  startWatching: (options?: StartWatchingOptions) => Promise<void>;
  /** Stop any in-flight watch loop and return to 'idle' without a reading. */
  cancel: () => void;
  /** Clear any prior reading/error and reset the freshness anchor. */
  reset: () => void;
}

/**
 * Counterpart of ``useBpCuffWatch`` for the Omron HBF-222T weight scale:
 * resolves with a fresh weight reading the patient just took at the booth.
 */
export function useScaleWatch(): UseScaleWatchResult {
  const [status, setStatus] = useState<ScaleWatchStatus>('idle');
  const [stage, setStage] = useState<ScaleWatchStage>('step-on');
  const [reading, setReading] = useState<WeightScaleFetchResponse | null>(null);
  const [errorKey, setErrorKey] = useState<string | null>(null);

  // Invalidates any in-flight watch loop when the caller unmounts, cancels,
  // or restarts: each loop captures the token at start and stops as soon
  // as it no longer matches.
  const watchTokenRef = useRef(0);
  useEffect(() => {
    return () => {
      watchTokenRef.current += 1;
    };
  }, []);

  // Freshness anchor of the current measurement attempt. Retries reuse it
  // so a measurement that finished during a detection hiccup still counts.
  const anchorRef = useRef(0);
  // Newest sequence known BEFORE this attempt — passed to every watch call
  // so a reading that syncs between two long-polls is returned by the next
  // one instead of being silently re-baselined away.
  const sinceSeqRef = useRef<number | null>(null);

  const applyReading = useCallback((result: WeightScaleFetchResponse) => {
    if (result.sequence != null) sinceSeqRef.current = result.sequence;
    setReading(result);
    setStatus('idle');
  }, []);

  const cancel = useCallback(() => {
    watchTokenRef.current += 1;
    setStatus('idle');
  }, []);

  const reset = useCallback(() => {
    watchTokenRef.current += 1;
    anchorRef.current = 0;
    sinceSeqRef.current = null;
    setStatus('idle');
    setStage('step-on');
    setReading(null);
    setErrorKey(null);
  }, []);

  const startWatching = useCallback(
    async (options?: StartWatchingOptions) => {
      const resume = options?.resume ?? false;
      const deadlineMs = options?.deadlineMs ?? WATCH_DEADLINE_MS;
      const token = ++watchTokenRef.current;
      if (!resume || !anchorRef.current) {
        anchorRef.current = Date.now();
      }
      const anchor = anchorRef.current;
      const startedAt = Date.now();
      setErrorKey(null);
      setStatus('watching');
      setStage('step-on');

      const isFresh = (result: WeightScaleFetchResponse) => {
        if (result.status !== 'ok' || !result.measured_at) return false;
        return new Date(result.measured_at).getTime() >= anchor - CLOCK_SKEW_MS;
      };

      // A fetch is cheap in file mode and covers a measurement that synced
      // before the watch armed (the patient steps on the scale in seconds).
      // The anchor check keeps stale history from a prior patient out; a
      // stale reading's sequence becomes the novelty baseline instead.
      try {
        const result = await api.fetchWeightScale();
        if (watchTokenRef.current !== token) return;
        if (isFresh(result)) {
          applyReading(result);
          return;
        }
        if (result.status === 'ok' && result.sequence != null) {
          sinceSeqRef.current = result.sequence;
        }
      } catch {
        // Fall through to the watch loop.
      }
      if (watchTokenRef.current !== token) return;

      if (!resume) {
        await sleep(STEP_ON_MS);
        if (watchTokenRef.current !== token) return;
      }
      setStage('reading');

      while (watchTokenRef.current === token) {
        if (Date.now() - startedAt > deadlineMs) {
          setErrorKey('scaleErrNoMeasurement');
          setStatus('error');
          return;
        }
        try {
          const result = await api.watchWeightScale(
            WATCH_CALL_TIMEOUT_S,
            sinceSeqRef.current,
          );
          if (watchTokenRef.current !== token) return;
          if (result.status === 'ok' && result.weight_kg != null) {
            // Server-guaranteed new-by-sequence — accept regardless of the
            // scale clock (which resets on battery change).
            applyReading(result);
            return;
          }
          if (result.status === 'not_seen') {
            // Nothing new within the window — re-arm with no delay.
            continue;
          }
          // busy / device_not_found etc.: brief pause, then retry below.
        } catch {
          // Network hiccup — retry until the deadline.
        }
        if (watchTokenRef.current !== token) return;
        await sleep(WATCH_RETRY_DELAY_MS);
      }
    },
    [applyReading],
  );

  return { status, stage, reading, errorKey, startWatching, cancel, reset };
}
