import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import type { BloodPressureFetchResponse } from '../api/types';
import { Layout } from '../components/Layout';
import { useLanguage, useSessionStorage } from '../hooks/useSession';
import { prewarmVoiceCall } from '../hooks/voicePrewarm';

type VitalsStep = 'form' | 'watching' | 'error';
type WatchStage = 'press-start' | 'measuring' | 'reading';

/** How long the "press START now" prompt stays before switching copy. */
const PRESS_START_MS = 8_000;
/**
 * Short head start before arming the watch: the cuff is silent while it
 * inflates anyway, and the backend now detects the exact moment the
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

function HeartIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z" />
    </svg>
  );
}

const parseNum = (v: string): number | undefined => {
  const n = Number.parseFloat(v);
  return Number.isFinite(n) ? n : undefined;
};

/**
 * Pre-conversation vitals gate. Reached from the landing page with
 * ?mode=call|chat after the session is created. Every booth patient must
 * supply blood pressure (typed manually OR measured on the Omron cuff next
 * to the kiosk), pulse, weight, and height before continuing — there is no
 * skip. Temperature is NOT collected here; the screening engine requests it
 * on-demand mid-interview only when a fever rule needs it.
 */
export function VitalsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { language, setLanguage } = useLanguage();
  const { sessionId } = useSessionStorage();
  const [step, setStep] = useState<VitalsStep>('form');
  const [watchStage, setWatchStage] = useState<WatchStage>('press-start');
  const [errorKey, setErrorKey] = useState<string>('vitalsErrGeneric');
  const [saving, setSaving] = useState(false);
  const [showRequired, setShowRequired] = useState(false);

  // Required booth vitals (all typed strings; BP may be filled by the cuff).
  const [systolic, setSystolic] = useState('');
  const [diastolic, setDiastolic] = useState('');
  const [pulse, setPulse] = useState('');
  const [weightKg, setWeightKg] = useState('');
  const [heightCm, setHeightCm] = useState('');
  // The cuff reading that populated BP, if any — lets us tag the write-back
  // as a device measurement (with its id/timestamp) unless the patient has
  // since edited the numbers.
  const [reading, setReading] = useState<BloodPressureFetchResponse | null>(null);

  // Invalidates any in-flight watch loop when the user navigates away,
  // cancels, or restarts: each loop captures the token at start and
  // stops as soon as it no longer matches.
  const watchTokenRef = useRef(0);
  useEffect(() => {
    return () => {
      watchTokenRef.current += 1;
    };
  }, []);

  const mode = searchParams.get('mode') === 'call' ? 'call' : 'chat';

  const proceed = () => {
    watchTokenRef.current += 1;
    if (mode === 'call') {
      void prewarmVoiceCall();
    }
    navigate(mode === 'call' ? '/call' : '/chat');
  };

  // Freshness anchor of the current measurement attempt. Retries reuse it
  // so a measurement that finished during a detection hiccup still counts.
  const anchorRef = useRef(0);

  const applyReading = (result: BloodPressureFetchResponse) => {
    setReading(result);
    if (result.systolic != null) setSystolic(String(result.systolic));
    if (result.diastolic != null) setDiastolic(String(result.diastolic));
    if (result.pulse_bpm != null) setPulse(String(result.pulse_bpm));
    setStep('form');
  };

  /**
   * Hands-free measurement flow: prompt the patient to press START, then
   * arm a backend long-poll that listens for the cuff's own
   * "measurement finished" Bluetooth broadcast and pulls the reading the
   * moment it appears — no blind timed polling. The freshness anchor
   * still decides whether a returned reading belongs to THIS attempt.
   */
  const startWatching = async (resume = false) => {
    const token = ++watchTokenRef.current;
    if (!resume || !anchorRef.current) {
      anchorRef.current = Date.now();
    }
    const anchor = anchorRef.current;
    const startedAt = Date.now();
    setStep('watching');

    if (resume) {
      // The patient likely already measured — try a direct fetch first,
      // in case the cuff's post-measurement broadcast window already
      // passed (then only a fetch attempt can still reach it).
      setWatchStage('reading');
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
      setWatchStage('press-start');
      await sleep(PRESS_START_MS);
      if (watchTokenRef.current !== token) return;
      setWatchStage('measuring');
      await sleep(WATCH_GRACE_MS - PRESS_START_MS);
    }

    while (watchTokenRef.current === token) {
      if (Date.now() - startedAt > WATCH_DEADLINE_MS) {
        setErrorKey('vitalsErrNoMeasurement');
        setStep('error');
        return;
      }
      setWatchStage('measuring');
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
  };

  const sys = parseNum(systolic);
  const dia = parseNum(diastolic);
  const pul = parseNum(pulse);
  const wgt = parseNum(weightKg);
  const hgt = parseNum(heightCm);
  const formComplete =
    sys !== undefined &&
    dia !== undefined &&
    pul !== undefined &&
    wgt !== undefined &&
    hgt !== undefined;

  const saveAndContinue = async () => {
    if (!formComplete || sys === undefined || dia === undefined) {
      setShowRequired(true);
      return;
    }
    setSaving(true);
    try {
      if (sessionId) {
        // Tag as a device reading only if the cuff filled BP and the patient
        // hasn't edited it since; otherwise it's a manual booth entry.
        const fromDevice =
          reading != null &&
          reading.systolic === sys &&
          reading.diastolic === dia;
        await api.updateSessionVitals(sessionId, {
          systolic: sys,
          diastolic: dia,
          pulse_bpm: pul,
          weight_kg: wgt,
          height_cm: hgt,
          measured_at: fromDevice ? reading?.measured_at : undefined,
          source: fromDevice ? 'device' : 'manual',
          reading_id: fromDevice ? reading?.reading_id : undefined,
        });
      }
    } catch {
      // Non-fatal: the conversation can continue without stored vitals.
    } finally {
      setSaving(false);
      proceed();
    }
  };

  return (
    <Layout language={language} onLanguageChange={setLanguage}>
      <section className="landing">
        <div className="landing-card vitals-card">
          <span className="landing-badge">{t('vitalsKicker')}</span>

          {step === 'form' && (
            <>
              <span className="vitals-icon">
                <HeartIcon />
              </span>
              <h1>{t('vitalsFormTitle')}</h1>
              <p className="landing-tagline">{t('vitalsFormHint')}</p>

              <div className="vitals-form">
                <div className="vitals-form-section">
                  <div className="vitals-form-section-head">
                    <span className="vitals-form-section-title">{t('vitalsBpSection')}</span>
                    <button
                      type="button"
                      className="vitals-measure-link"
                      onClick={() => void startWatching()}
                    >
                      {t('vitalsMeasureCuff')}
                    </button>
                  </div>
                  <div className="vitals-form-grid">
                    <label className="vitals-extra-field">
                      <span>{t('vitalsSystolic')} ({t('vitalsUnitMmhg')})</span>
                      <input
                        type="number"
                        inputMode="numeric"
                        min={40}
                        max={300}
                        value={systolic}
                        onChange={(e) => setSystolic(e.target.value)}
                      />
                    </label>
                    <label className="vitals-extra-field">
                      <span>{t('vitalsDiastolic')} ({t('vitalsUnitMmhg')})</span>
                      <input
                        type="number"
                        inputMode="numeric"
                        min={20}
                        max={200}
                        value={diastolic}
                        onChange={(e) => setDiastolic(e.target.value)}
                      />
                    </label>
                    <label className="vitals-extra-field">
                      <span>{t('vitalsPulse')} ({t('vitalsUnitBpm')})</span>
                      <input
                        type="number"
                        inputMode="numeric"
                        min={20}
                        max={250}
                        value={pulse}
                        onChange={(e) => setPulse(e.target.value)}
                      />
                    </label>
                  </div>
                </div>

                <div className="vitals-form-section">
                  <span className="vitals-form-section-title">{t('vitalsBodySection')}</span>
                  <div className="vitals-form-grid cols-2">
                    <label className="vitals-extra-field">
                      <span>{t('vitalsWeight')}</span>
                      <input
                        type="number"
                        inputMode="decimal"
                        min={1}
                        max={400}
                        value={weightKg}
                        onChange={(e) => setWeightKg(e.target.value)}
                      />
                    </label>
                    <label className="vitals-extra-field">
                      <span>{t('vitalsHeight')}</span>
                      <input
                        type="number"
                        inputMode="decimal"
                        min={1}
                        max={272}
                        value={heightCm}
                        onChange={(e) => setHeightCm(e.target.value)}
                      />
                    </label>
                  </div>
                </div>
              </div>

              {showRequired && !formComplete && (
                <p className="error-text">{t('vitalsRequiredError')}</p>
              )}

              <div className="vitals-actions">
                <button
                  type="button"
                  className="primary-btn"
                  onClick={() => void saveAndContinue()}
                  disabled={saving || !formComplete}
                >
                  {saving ? t('loading') : t('vitalsContinue')}
                </button>
              </div>
            </>
          )}

          {step === 'watching' && (
            <>
              <span className="vitals-icon vitals-icon-pulse">
                <HeartIcon />
              </span>
              {watchStage === 'press-start' ? (
                <>
                  <h1 className="vitals-press-start">{t('vitalsWatchPressStart')}</h1>
                  <p className="landing-tagline">{t('vitalsWatchPressStartHint')}</p>
                </>
              ) : (
                <>
                  <h1>
                    {watchStage === 'measuring'
                      ? t('vitalsWatchMeasuring')
                      : t('vitalsWatchReading')}
                  </h1>
                  <p className="landing-tagline">{t('vitalsWatchMeasuringHint')}</p>
                </>
              )}
              <div className="vitals-progress">
                <div className="vitals-progress-bar" />
              </div>
              <button
                type="button"
                className="vitals-skip"
                onClick={() => {
                  watchTokenRef.current += 1;
                  setStep('form');
                }}
              >
                {t('vitalsEnterManually')}
              </button>
            </>
          )}

          {step === 'error' && (
            <>
              <h1>{t('vitalsErrorTitle')}</h1>
              <p className="error-text">{t(errorKey)}</p>
              <div className="vitals-actions">
                <button
                  type="button"
                  className="primary-btn"
                  onClick={() => void startWatching(true)}
                >
                  {t('vitalsRetry')}
                </button>
                <button
                  type="button"
                  className="secondary-btn"
                  onClick={() => {
                    watchTokenRef.current += 1;
                    setStep('form');
                  }}
                >
                  {t('vitalsEnterManually')}
                </button>
              </div>
            </>
          )}
        </div>
      </section>
    </Layout>
  );
}
