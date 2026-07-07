import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import type { BloodPressureFetchResponse } from '../api/types';
import { Layout } from '../components/Layout';
import { useLanguage, useSessionStorage } from '../hooks/useSession';
import { prewarmVoiceCall } from '../hooks/voicePrewarm';

type VitalsStep = 'ask' | 'measure' | 'watching' | 'result' | 'error';
type WatchStage = 'press-start' | 'measuring' | 'reading';

/** How long the "press START now" prompt stays before switching copy. */
const PRESS_START_MS = 8_000;
/**
 * No BLE attempts during the first stretch: the cuff needs to begin
 * inflating undisturbed, and it isn't connectable mid-measurement anyway.
 */
const WATCH_GRACE_MS = 35_000;
/** Give up on auto-detection after this long and show a retry screen. */
const WATCH_DEADLINE_MS = 4 * 60_000;
const WATCH_RETRY_DELAY_MS = 5_000;
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

/**
 * Pre-conversation blood-pressure gate. Reached from the landing page
 * with ?mode=call|chat after the session is created. The patient either
 * confirms they know their blood pressure (and continues straight to
 * the conversation), or measures on the Omron cuff next to the kiosk
 * and lets the backend pull the reading over Bluetooth (omblepy).
 */
export function VitalsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { language, setLanguage } = useLanguage();
  const { sessionId } = useSessionStorage();
  const [step, setStep] = useState<VitalsStep>('ask');
  const [watchStage, setWatchStage] = useState<WatchStage>('press-start');
  const [reading, setReading] = useState<BloodPressureFetchResponse | null>(null);
  const [errorKey, setErrorKey] = useState<string>('vitalsErrGeneric');
  const [saving, setSaving] = useState(false);

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

  /**
   * Hands-free measurement flow: prompt the patient to press START, then
   * quietly poll the cuff until a reading measured AFTER the anchor
   * appears. The cuff cannot be started over BLE, but detecting the
   * finished measurement automatically removes every other screen touch.
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
      // The patient likely already measured — poll right away.
      setWatchStage('reading');
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
      setWatchStage('reading');
      try {
        const result = await api.fetchBloodPressure(sessionId);
        if (watchTokenRef.current !== token) return;
        if (result.status === 'ok' && result.measured_at) {
          const measuredMs = new Date(result.measured_at).getTime();
          if (measuredMs >= anchor - CLOCK_SKEW_MS) {
            setReading(result);
            setStep('result');
            return;
          }
          // Stale record from before this measurement — keep waiting.
        }
        // device_not_found / busy mid-measurement are expected; retry.
      } catch {
        // Network hiccup — retry until the deadline.
      }
      if (watchTokenRef.current !== token) return;
      setWatchStage('measuring');
      await sleep(WATCH_RETRY_DELAY_MS);
    }
  };

  const saveAndContinue = async () => {
    if (!reading || reading.systolic == null || reading.diastolic == null) {
      proceed();
      return;
    }
    setSaving(true);
    try {
      if (sessionId) {
        await api.updateSessionVitals(sessionId, {
          systolic: reading.systolic,
          diastolic: reading.diastolic,
          pulse_bpm: reading.pulse_bpm,
          measured_at: reading.measured_at,
          source: 'device',
          reading_id: reading.reading_id,
        });
      }
    } catch {
      // Non-fatal: the conversation can continue without stored vitals.
    } finally {
      setSaving(false);
      proceed();
    }
  };

  const measuredTime = reading?.measured_at
    ? new Date(reading.measured_at).toLocaleTimeString(language === 'th' ? 'th-TH' : 'en-US', {
        hour: '2-digit',
        minute: '2-digit',
      })
    : null;

  return (
    <Layout language={language} onLanguageChange={setLanguage}>
      <section className="landing">
        <div className="landing-card vitals-card">
          <span className="landing-badge">{t('vitalsKicker')}</span>

          {step === 'ask' && (
            <>
              <span className="vitals-icon">
                <HeartIcon />
              </span>
              <h1>{t('vitalsAskQuestion')}</h1>
              <p className="landing-tagline">{t('vitalsAskHint')}</p>
              <div className="vitals-actions">
                <button type="button" className="primary-btn" onClick={proceed}>
                  {t('vitalsKnowYes')}
                </button>
                <button
                  type="button"
                  className="secondary-btn"
                  onClick={() => setStep('measure')}
                >
                  {t('vitalsKnowNo')}
                </button>
              </div>
              <button type="button" className="vitals-skip" onClick={proceed}>
                {t('vitalsSkip')}
              </button>
            </>
          )}

          {step === 'measure' && (
            <>
              <h1>{t('vitalsMeasureTitle')}</h1>
              <ol className="vitals-steps">
                <li>{t('vitalsStep1')}</li>
                <li>{t('vitalsStep2')}</li>
                <li>{t('vitalsStep3')}</li>
              </ol>
              <div className="vitals-actions">
                <button type="button" className="primary-btn" onClick={() => void startWatching()}>
                  {t('vitalsReadyButton')}
                </button>
                <button type="button" className="secondary-btn" onClick={() => setStep('ask')}>
                  {t('vitalsBack')}
                </button>
              </div>
              <button type="button" className="vitals-skip" onClick={proceed}>
                {t('vitalsSkip')}
              </button>
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
              <button type="button" className="vitals-skip" onClick={proceed}>
                {t('vitalsSkip')}
              </button>
            </>
          )}

          {step === 'result' && reading && (
            <>
              <h1>{t('vitalsResultTitle')}</h1>
              <div className="vitals-readings">
                <div className="vitals-reading">
                  <span className="vitals-value">{reading.systolic}</span>
                  <span className="vitals-label">{t('vitalsSystolic')}</span>
                  <span className="vitals-unit">{t('vitalsUnitMmhg')}</span>
                </div>
                <div className="vitals-reading">
                  <span className="vitals-value">{reading.diastolic}</span>
                  <span className="vitals-label">{t('vitalsDiastolic')}</span>
                  <span className="vitals-unit">{t('vitalsUnitMmhg')}</span>
                </div>
                <div className="vitals-reading">
                  <span className="vitals-value">{reading.pulse_bpm}</span>
                  <span className="vitals-label">{t('vitalsPulse')}</span>
                  <span className="vitals-unit">{t('vitalsUnitBpm')}</span>
                </div>
              </div>
              {measuredTime && (
                <p className="muted vitals-measured-at">
                  {t('vitalsMeasuredAt', { time: measuredTime })}
                </p>
              )}
              {reading.is_recent === false && (
                <p className="vitals-warning">{t('vitalsStaleWarning')}</p>
              )}
              {reading.irregular_heartbeat && (
                <p className="vitals-warning">{t('vitalsIrregular')}</p>
              )}
              <div className="vitals-actions">
                <button
                  type="button"
                  className="primary-btn"
                  onClick={() => void saveAndContinue()}
                  disabled={saving}
                >
                  {saving ? t('loading') : t('vitalsContinue')}
                </button>
                <button
                  type="button"
                  className="secondary-btn"
                  onClick={() => setStep('measure')}
                  disabled={saving}
                >
                  {t('vitalsMeasureAgain')}
                </button>
              </div>
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
                <button type="button" className="secondary-btn" onClick={proceed}>
                  {t('vitalsSkip')}
                </button>
              </div>
              <button type="button" className="vitals-skip" onClick={() => setStep('measure')}>
                {t('vitalsBack')}
              </button>
            </>
          )}
        </div>
      </section>
    </Layout>
  );
}
