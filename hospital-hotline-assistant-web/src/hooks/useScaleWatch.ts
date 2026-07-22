import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { WeightScaleFetchResponse } from '../api/types';

export type ScaleWatchStatus = 'idle' | 'watching' | 'error';
export type ScaleWatchStage = 'step-on' | 'reading';

/** How long the "step on the scale now" prompt stays before switching copy. */
const STEP_ON_MS = 5_000;
/** Give up on auto-detection after this long and show a retry screen. */
const WATCH_DEADLINE_MS = 3 * 60_000;
/** Server-side long-poll window per watch call. */
const WATCH_CALL_TIMEOUT_S = 25;
/** Pause between calls only after unexpected statuses/network errors. */
const WATCH_RETRY_DELAY_MS = 1_000;
/** Tolerated scale-vs-kiosk clock drift when judging reading freshness. */
const CLOCK_SKEW_MS = 90_000;

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export interface UseScaleWatchResult {
  status: ScaleWatchStatus;
  stage: ScaleWatchStage;
  reading: WeightScaleFetchResponse | null;
  /** Set only when ``status === 'error'``; an i18n key for the message. */
  errorKey: string | null;
  /**
   * Hands-free measurement flow: prompt the patient to step on the scale,
   * then long-poll the backend, which resolves the moment the scale syncs
   * a new measurement (via the omscale daemon's latest-file or a direct
   * BLE fetch, depending on the API's SCALE_READ_MODE). The freshness
   * anchor decides whether a returned reading belongs to THIS attempt, so
   * a measurement that finished before the watch armed still counts.
   * Pass ``resume: true`` to retry after an error without resetting the
   * freshness anchor.
   */
  startWatching: (resume?: boolean) => Promise<void>;
  /** Stop any in-flight watch loop and return to 'idle' without a reading. */
  cancel: () => void;
  /** Clear any prior reading/error and reset the freshness anchor. */
  reset: () => void;
}

/**
 * Counterpart of ``useBpCuffWatch`` for the Omron weight scale: resolves
 * with a fresh weight reading the patient just took at the booth.
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

  const applyReading = useCallback((result: WeightScaleFetchResponse) => {
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
    setStatus('idle');
    setStage('step-on');
    setReading(null);
    setErrorKey(null);
  }, []);

  const startWatching = useCallback(
    async (resume = false) => {
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
      // The anchor check keeps stale history from a prior patient out.
      try {
        const result = await api.fetchWeightScale();
        if (watchTokenRef.current !== token) return;
        if (isFresh(result)) {
          applyReading(result);
          return;
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
        if (Date.now() - startedAt > WATCH_DEADLINE_MS) {
          setErrorKey('scaleErrNoMeasurement');
          setStatus('error');
          return;
        }
        try {
          const result = await api.watchWeightScale(WATCH_CALL_TIMEOUT_S);
          if (watchTokenRef.current !== token) return;
          if (isFresh(result)) {
            applyReading(result);
            return;
          }
          if (result.status === 'not_seen' || result.status === 'ok') {
            // Nothing new (or stale history) within the window — re-arm
            // with no delay.
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
