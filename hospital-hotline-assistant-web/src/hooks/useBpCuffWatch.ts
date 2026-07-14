import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { BloodPressureFetchResponse } from '../api/types';

export type BpCuffWatchStatus = 'idle' | 'watching' | 'error';
export type BpCuffWatchStage = 'press-start' | 'measuring' | 'reading';

/** How long the "press START now" prompt stays before switching copy. */
const PRESS_START_MS = 8_000;
/**
 * Short head start before arming the watch: the cuff is silent while it
 * inflates anyway, and the backend detects the exact moment the
 * measurement finishes (the cuff's own BLE broadcast), so this no longer
 * needs to cover the whole measurement.
 */
const WATCH_GRACE_MS = 15_000;
/** Give up on auto-detection after this long and show a retry screen. */
const WATCH_DEADLINE_MS = 4 * 60_000;
/** Server-side long-poll window per watch call. */
const WATCH_CALL_TIMEOUT_S = 25;
/** Pause between calls only after unexpected statuses/network errors. */
const WATCH_RETRY_DELAY_MS = 1_000;
/** Tolerated cuff-vs-kiosk clock drift when judging reading freshness. */
const CLOCK_SKEW_MS = 90_000;

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export interface UseBpCuffWatchResult {
  status: BpCuffWatchStatus;
  stage: BpCuffWatchStage;
  reading: BloodPressureFetchResponse | null;
  /** Set only when ``status === 'error'``; an i18n key for the message. */
  errorKey: string | null;
  /**
   * Hands-free measurement flow: prompt the patient to press START, then
   * arm a backend long-poll that listens for the cuff's own
   * "measurement finished" Bluetooth broadcast and pulls the reading the
   * moment it appears — no blind timed polling. The freshness anchor
   * still decides whether a returned reading belongs to THIS attempt.
   * Pass ``resume: true`` to retry after an error without resetting the
   * freshness anchor (a measurement that finished during the hiccup
   * still counts).
   */
  startWatching: (resume?: boolean) => Promise<void>;
  /** Stop any in-flight watch loop and return to 'idle' without a reading. */
  cancel: () => void;
  /** Clear any prior reading/error and reset the freshness anchor. */
  reset: () => void;
  /** Manually apply a reading (e.g. one obtained outside the watch loop). */
  applyReading: (result: BloodPressureFetchResponse) => void;
}

/**
 * Extracted from the pre-conversation vitals gate: watches the Omron cuff
 * over the backend's long-poll endpoint and resolves with a fresh reading.
 * Preserves the device-provenance rules the caller needs to tag a
 * write-back as ``source: 'device'`` (reading id + measured_at survive on
 * the returned ``reading``).
 */
export function useBpCuffWatch(sessionId?: string | null): UseBpCuffWatchResult {
  const [status, setStatus] = useState<BpCuffWatchStatus>('idle');
  const [stage, setStage] = useState<BpCuffWatchStage>('press-start');
  const [reading, setReading] = useState<BloodPressureFetchResponse | null>(null);
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

  const applyReading = useCallback((result: BloodPressureFetchResponse) => {
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
    setStage('press-start');
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

      if (resume) {
        // The patient likely already measured — try a direct fetch first,
        // in case the cuff's post-measurement broadcast window already
        // passed (then only a fetch attempt can still reach it).
        setStage('reading');
        try {
          const result = await api.fetchBloodPressure(sessionId);
          if (watchTokenRef.current !== token) return;
          if (result.status === 'ok' && result.measured_at) {
            const measuredMs = new Date(result.measured_at).getTime();
            if (measuredMs >= anchor - CLOCK_SKEW_MS) {
              applyReading(result);
              return;
            }
          }
        } catch {
          // Fall through to the watch loop.
        }
      } else {
        setStage('press-start');
        await sleep(PRESS_START_MS);
        if (watchTokenRef.current !== token) return;
        setStage('measuring');
        await sleep(WATCH_GRACE_MS - PRESS_START_MS);
      }

      while (watchTokenRef.current === token) {
        if (Date.now() - startedAt > WATCH_DEADLINE_MS) {
          setErrorKey('vitalsErrNoMeasurement');
          setStatus('error');
          return;
        }
        setStage('measuring');
        try {
          const result = await api.watchBloodPressure(sessionId, WATCH_CALL_TIMEOUT_S);
          if (watchTokenRef.current !== token) return;
          if (result.status === 'ok' && result.measured_at) {
            const measuredMs = new Date(result.measured_at).getTime();
            if (measuredMs >= anchor - CLOCK_SKEW_MS) {
              applyReading(result);
              return;
            }
            // Stale record from before this measurement — keep waiting.
          }
          if (result.status === 'not_seen') {
            // Nothing broadcast within the window — re-arm with no delay.
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
    [sessionId, applyReading],
  );

  return { status, stage, reading, errorKey, startWatching, cancel, reset, applyReading };
}
