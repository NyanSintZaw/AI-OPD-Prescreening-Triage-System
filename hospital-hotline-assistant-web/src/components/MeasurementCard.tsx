import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import type { VitalBoundsOut } from '../api/types';
import type { AppLanguage } from '../i18n/resources';
import { useBpCuffWatch } from '../hooks/useBpCuffWatch';
import { useSessionStorage } from '../hooks/useSession';

export interface MeasurementCardProps {
  /** Vital the screening engine is asking the booth to measure right now
   *  (``'temp' | 'sbp' | 'weight'`` — see ``VitalName`` on the backend). */
  vital: string;
  language?: AppLanguage;
  /** Fired once the reading is saved on the session; receives a short
   *  patient-utterance-shaped string the caller should send as the next
   *  conversation turn (e.g. ``"37.2 °C"``, ``"BP 118/76"``). */
  onSubmit: (continuationText: string) => void | Promise<void>;
  /** Fired when a first crisis BP reading opened the 15-minute rest window:
   *  the assessment pauses and the patient is told to rest and come back
   *  (the reading is provisional — no conversation turn is sent). Also fired
   *  from the resting screen's "I'll come back" button. When omitted, the
   *  card falls back to an inline resting countdown. */
  onRest?: (secondsRemaining: number) => void;
  onCancel?: () => void;
  disabled?: boolean;
}

type SbpChoice = 'unset' | 'machine' | 'manual';

const parseNum = (v: string): number | undefined => {
  const n = Number.parseFloat(v);
  return Number.isFinite(n) ? n : undefined;
};

// Physiologically plausible input ranges (HTML min/max don't stop typed
// values, so submits re-check). Out-of-range gets its own message —
// "fill in all fields" would gaslight a patient whose fields ARE filled.
//
// The live numbers come from the active criteria version via
// GET /screening/vital-bounds (see docs/vital-bounds.md); these are only the
// offline fallback for when that call fails. Keep them in sync with
// default_vital_bounds() in criteria_models.py.
const FALLBACK_BOUNDS: Record<string, { min: number; max: number }> = {
  sbp: { min: 50, max: 300 },
  dbp: { min: 20, max: 200 },
  hr: { min: 20, max: 250 },
  temp: { min: 30, max: 45 },
  weight: { min: 1, max: 400 },
  height: { min: 30, max: 272 },
};

/**
 * Inline card the booth shows mid-interview when the screening engine asks
 * for a reading it needs right now (``awaiting_measurement`` on chat turns,
 * the ``measurement_request`` frame on voice calls). Handles the three
 * vitals the engine can request: temperature, blood pressure (machine or
 * manual), and weight+height together.
 */
export function MeasurementCard({ vital, language, onSubmit, onRest, onCancel, disabled }: MeasurementCardProps) {
  const { t, i18n } = useTranslation();
  const { sessionId } = useSessionStorage();
  const [saving, setSaving] = useState(false);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  // Nurse-authored rejection wording from the criteria; takes precedence over
  // the generic errorKey message when set.
  const [errorText, setErrorText] = useState<string | null>(null);
  const [restSeconds, setRestSeconds] = useState<number | null>(null);
  const [bounds, setBounds] = useState<VitalBoundsOut | null>(null);
  const lang = language ?? (i18n.language === 'en' ? 'en' : 'th');

  useEffect(() => {
    let cancelled = false;
    api
      .getVitalBounds()
      .then((data) => {
        if (!cancelled) setBounds(data);
      })
      .catch(() => {
        /* fall back to FALLBACK_BOUNDS with the generic range message */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const boundFor = (name: string) => bounds?.bounds?.[name] ?? FALLBACK_BOUNDS[name];

  /** Range-check one value; on failure show the authored reason and return false. */
  const accept = (name: string, value: number): boolean => {
    const bound = boundFor(name);
    if (!bound || (value >= bound.min && value <= bound.max)) return true;
    const authored = bounds?.bounds?.[name];
    setErrorText(authored ? (lang === 'en' ? authored.retry_text_en : authored.retry_text_th) : null);
    setErrorKey('vitalsRangeError');
    return false;
  };

  const rejectCross = (checkId: string) => {
    const check = bounds?.cross_checks?.[checkId];
    setErrorText(check ? (lang === 'en' ? check.text_en : check.text_th) : null);
    setErrorKey(checkId === 'sbp_le_dbp' ? 'vitalsErrSwapped' : 'vitalsRangeError');
  };

  const [tempValue, setTempValue] = useState('');
  const [tempFetching, setTempFetching] = useState(false);
  const [deviceTemp, setDeviceTemp] = useState<number | null>(null);
  // Set when the patient backs out of a device fetch: the in-flight
  // long-poll result is ignored instead of aborted (kiosk has one station).
  const tempCancelRef = useRef(false);

  const [sbpChoice, setSbpChoice] = useState<SbpChoice>('unset');
  const [systolic, setSystolic] = useState('');
  const [diastolic, setDiastolic] = useState('');
  const [pulse, setPulse] = useState('');
  const cuff = useBpCuffWatch(sessionId);

  const [weightKg, setWeightKg] = useState('');
  const [heightCm, setHeightCm] = useState('');

  // Reset all local state whenever the engine asks for a different vital
  // (or re-asks for the same one on a later turn).
  useEffect(() => {
    setSaving(false);
    setErrorKey(null);
    setErrorText(null);
    setRestSeconds(null);
    setTempValue('');
    setTempFetching(false);
    setDeviceTemp(null);
    tempCancelRef.current = true;
    setSbpChoice('unset');
    setSystolic('');
    setDiastolic('');
    setPulse('');
    setWeightKg('');
    setHeightCm('');
    cuff.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vital]);

  // Poll rest status when asking for BP so a crisis timer from an earlier
  // reading (possibly in a prior kiosk visit for the same HN) blocks remeasure.
  useEffect(() => {
    if (vital !== 'sbp' || !sessionId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const status = await api.getBpRestStatus(sessionId);
        if (cancelled) return;
        if (status.resting && status.seconds_remaining > 0) {
          setRestSeconds(status.seconds_remaining);
          setErrorKey('vitalsErrResting');
        } else {
          setRestSeconds(null);
          setErrorKey((prev) => (prev === 'vitalsErrResting' ? null : prev));
        }
      } catch {
        /* ignore — measurement still possible if status check fails */
      }
    };
    void tick();
    const id = window.setInterval(() => void tick(), 5000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [vital, sessionId]);

  // The cuff hook resolved a reading — auto-fill the (still editable)
  // fields, same as the pre-conversation vitals gate used to.
  useEffect(() => {
    if (!cuff.reading) return;
    if (cuff.reading.systolic != null) setSystolic(String(cuff.reading.systolic));
    if (cuff.reading.diastolic != null) setDiastolic(String(cuff.reading.diastolic));
    if (cuff.reading.pulse_bpm != null) setPulse(String(cuff.reading.pulse_bpm));
  }, [cuff.reading]);

  const busy = saving || Boolean(disabled) || (vital === 'sbp' && restSeconds != null && restSeconds > 0);

  const startTempDevice = async () => {
    setErrorKey(null);
    setErrorText(null);
    setTempFetching(true);
    tempCancelRef.current = false;
    try {
      const result = await api.fetchTemperature(sessionId, 60);
      if (tempCancelRef.current) return;
      if (result.status === 'ok' && result.temperature_c != null) {
        setDeviceTemp(result.temperature_c);
        setTempValue(String(result.temperature_c));
      } else if (result.status === 'timeout') {
        setErrorKey('measureTempDeviceTimeout');
      } else {
        setErrorKey('measureTempDeviceError');
      }
    } catch {
      if (!tempCancelRef.current) setErrorKey('measureTempDeviceError');
    } finally {
      if (!tempCancelRef.current) setTempFetching(false);
    }
  };

  const submitTemp = async () => {
    const value = parseNum(tempValue);
    if (value === undefined) {
      setErrorKey('vitalsRequiredError');
      return;
    }
    if (!accept('temp', value)) return;
    setSaving(true);
    setErrorKey(null);
    setErrorText(null);
    try {
      // A device reading used unedited was already persisted and merged
      // into the session vitals by the fetch endpoint — skip the manual
      // write-back so it isn't double-recorded.
      if (sessionId && !(deviceTemp != null && value === deviceTemp)) {
        await api.updateSessionMeasurement(sessionId, { vital: 'temp', value });
      }
    } catch {
      // Non-fatal: the continuation turn's extraction can still pick it up.
    } finally {
      setSaving(false);
    }
    await onSubmit(`${value} °C`);
  };

  const submitSbp = async (source: 'device' | 'manual') => {
    const sys = parseNum(systolic);
    const dia = parseNum(diastolic);
    const pul = parseNum(pulse);
    if (sys === undefined || dia === undefined) {
      setErrorKey('vitalsRequiredError');
      return;
    }
    if (!accept('sbp', sys) || !accept('dbp', dia)) return;
    if (pul !== undefined && !accept('hr', pul)) return;
    // The top number must exceed the bottom one — catches a swapped entry,
    // which is in range on both fields and so invisible to the checks above.
    if (sys <= dia) {
      rejectCross('sbp_le_dbp');
      return;
    }
    // Only tag as a device reading if the cuff filled BP and the patient
    // hasn't edited it since — otherwise it's effectively a manual entry.
    const fromDevice =
      source === 'device' &&
      cuff.reading != null &&
      cuff.reading.systolic === sys &&
      cuff.reading.diastolic === dia;
    setSaving(true);
    setErrorKey(null);
    try {
      if (sessionId) {
        const resp = await api.updateSessionVitals(sessionId, {
          systolic: sys,
          diastolic: dia,
          pulse_bpm: pul,
          measured_at: fromDevice ? cuff.reading?.measured_at ?? undefined : undefined,
          source: fromDevice ? 'device' : 'manual',
          reading_id: fromDevice ? cuff.reading?.reading_id ?? undefined : undefined,
        });
        if (resp.bp_recheck?.required) {
          // Crisis reading → 15-minute rest before re-measuring. Do NOT send
          // the provisional numbers into the conversation; pause instead.
          setSaving(false);
          const secs = resp.bp_recheck.seconds_remaining;
          if (onRest) {
            onRest(secs);
          } else {
            setRestSeconds(secs);
            setErrorKey('vitalsErrResting');
          }
          return;
        }
      }
    } catch (err) {
      // Could be a 409 (active rest window) — check before falling through,
      // so a blocked reading never leaks into the conversation as a turn.
      if (sessionId) {
        try {
          const status = await api.getBpRestStatus(sessionId);
          if (status.resting && status.seconds_remaining > 0) {
            setSaving(false);
            setRestSeconds(status.seconds_remaining);
            setErrorKey('vitalsErrResting');
            return;
          }
        } catch {
          /* status check failed — continue below */
        }
      }
      // A 4xx means the server REFUSED these numbers (implausible, or systolic
      // not above diastolic). Stop here: sending them on as a conversation
      // turn is exactly the leak the bounds exist to prevent.
      const status = (err as { status?: number } | null)?.status;
      if (status && status >= 400 && status < 500) {
        setSaving(false);
        setErrorKey('vitalsRangeError');
        return;
      }
      // Otherwise non-fatal: the conversation can continue without the
      // write-back.
    } finally {
      setSaving(false);
    }
    const text = pul !== undefined ? `BP ${sys}/${dia}, pulse ${pul}` : `BP ${sys}/${dia}`;
    await onSubmit(text);
  };

  const submitWeight = async () => {
    const wgt = parseNum(weightKg);
    const hgt = parseNum(heightCm);
    if (wgt === undefined || hgt === undefined) {
      setErrorKey('vitalsRequiredError');
      return;
    }
    if (!accept('weight', wgt) || !accept('height', hgt)) return;
    // Unit mix-up guard (height typed in metres, weight in pounds): both
    // numbers can be individually valid yet impossible together.
    const bmi = wgt / (hgt / 100) ** 2;
    if (!(bmi >= 5 && bmi <= 150)) {
      rejectCross('bmi_implausible');
      return;
    }
    setSaving(true);
    setErrorKey(null);
    setErrorText(null);
    try {
      if (sessionId) {
        await api.updateSessionMeasurement(sessionId, { vital: 'weight', value: wgt });
        await api.updateSessionMeasurement(sessionId, { vital: 'height', value: hgt });
      }
    } catch {
      // Non-fatal: the continuation turn's extraction can still pick it up.
    } finally {
      setSaving(false);
    }
    await onSubmit(`${wgt} kg, ${hgt} cm`);
  };

  // One renderer for every error slot: the authored rejection wording when we
  // have it, otherwise the generic i18n message.
  const errorNote = (errorText || errorKey) && (
    <p className="error-text" role="alert">
      {errorText
        ? errorText
        : errorKey === 'vitalsErrResting'
          ? t(errorKey, { minutes: Math.max(1, Math.ceil((restSeconds ?? 60) / 60)) })
          : t(errorKey!)}
    </p>
  );

  const cancelBtn = onCancel && (
    <button type="button" className="text-btn location-prompt-skip" onClick={onCancel} disabled={busy}>
      {t('measurementCancel')}
    </button>
  );

  // Measurements the engine asks for are required (it only asks when the
  // interview needs them) — there is deliberately no skip control.

  if (vital === 'temp') {
    if (tempFetching) {
      return (
        <div className="measurement-prompt-card">
          <p className="measurement-prompt-title">{t('measureTempDeviceWaiting')}</p>
          <p className="measurement-prompt-subtitle muted">{t('measureTempDeviceWaitingHint')}</p>
          <div className="vitals-progress">
            <div className="vitals-progress-bar" />
          </div>
          <div className="measurement-card-actions">
            <button
              type="button"
              className="text-btn location-prompt-skip"
              onClick={() => {
                tempCancelRef.current = true;
                setTempFetching(false);
              }}
            >
              {t('vitalsEnterManually')}
            </button>
            {cancelBtn}
          </div>
        </div>
      );
    }
    return (
      <div className="measurement-prompt-card">
        <p className="measurement-prompt-title">{t('measureTempTitle')}</p>
        <p className="measurement-prompt-subtitle muted">{t('measureTempHint')}</p>
        <div className="location-prompt-row">
          <input
            type="number"
            inputMode="decimal"
            className="location-prompt-input"
            placeholder="37.0"
            min={30}
            max={45}
            step={0.1}
            value={tempValue}
            onChange={(e) => setTempValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void submitTemp();
            }}
            disabled={busy}
            autoFocus
          />
          <button
            type="button"
            className="primary-btn location-prompt-confirm"
            onClick={() => void submitTemp()}
            disabled={busy || !tempValue.trim()}
          >
            {saving ? t('loading') : t('measureTempConfirm')}
          </button>
          {cancelBtn}
        </div>
        <div className="measurement-card-actions">
          <button
            type="button"
            className="secondary-btn"
            onClick={() => void startTempDevice()}
            disabled={busy}
          >
            {t('measureTempUseDevice')}
          </button>
        </div>
        {errorNote}
      </div>
    );
  }

  if (vital === 'sbp') {
    if (restSeconds != null && restSeconds > 0) {
      const minutes = Math.max(1, Math.ceil(restSeconds / 60));
      return (
        <div className="measurement-prompt-card">
          <p className="measurement-prompt-title">{t('measureRestTitle')}</p>
          <p className="error-text">{t('vitalsErrResting', { minutes })}</p>
          <p className="measurement-prompt-subtitle muted">{t('measureRestHint')}</p>
          {onRest && (
            <button
              type="button"
              className="primary-btn"
              onClick={() => onRest(restSeconds)}
            >
              {t('measureRestLeave')}
            </button>
          )}
          {cancelBtn}
        </div>
      );
    }

    if (sbpChoice === 'unset') {
      return (
        <div className="measurement-prompt-card">
          <p className="measurement-prompt-title">{t('measurementSbpChooseTitle')}</p>
          <div className="measurement-card-choice-row">
            <button
              type="button"
              className="secondary-btn"
              onClick={() => setSbpChoice('machine')}
              disabled={busy}
            >
              {t('measurementUseMachine')}
            </button>
            <button
              type="button"
              className="secondary-btn"
              onClick={() => setSbpChoice('manual')}
              disabled={busy}
            >
              {t('measurementEnterManually')}
            </button>
            {cancelBtn}
          </div>
        </div>
      );
    }

    if (sbpChoice === 'manual') {
      return (
        <div className="measurement-prompt-card">
          <p className="measurement-prompt-title">{t('vitalsMeasureTitle')}</p>
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
                disabled={busy}
                autoFocus
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
                disabled={busy}
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
                disabled={busy}
              />
            </label>
          </div>
          {errorNote}
          <div className="measurement-card-actions">
            <button
              type="button"
              className="primary-btn"
              onClick={() => void submitSbp('manual')}
              disabled={busy || !systolic.trim() || !diastolic.trim()}
            >
              {saving ? t('loading') : t('measurementConfirm')}
            </button>
            <button
              type="button"
              className="text-btn location-prompt-skip"
              onClick={() => setSbpChoice('unset')}
              disabled={busy}
            >
              {t('vitalsBack')}
            </button>
            {cancelBtn}
          </div>
        </div>
      );
    }

    // sbpChoice === 'machine'
    if (cuff.status === 'watching') {
      return (
        <div className="measurement-prompt-card">
          {cuff.stage === 'press-start' ? (
            <>
              <p className="measurement-prompt-title vitals-press-start">
                {t('vitalsWatchPressStart')}
              </p>
              <p className="measurement-prompt-subtitle muted">{t('vitalsWatchPressStartHint')}</p>
            </>
          ) : (
            <>
              <p className="measurement-prompt-title">
                {cuff.stage === 'measuring' ? t('vitalsWatchMeasuring') : t('vitalsWatchReading')}
              </p>
              <p className="measurement-prompt-subtitle muted">{t('vitalsWatchMeasuringHint')}</p>
            </>
          )}
          <div className="vitals-progress">
            <div className="vitals-progress-bar" />
          </div>
          <div className="measurement-card-actions">
            <button
              type="button"
              className="text-btn location-prompt-skip"
              onClick={() => {
                cuff.cancel();
                setSbpChoice('manual');
              }}
            >
              {t('vitalsEnterManually')}
            </button>
            {cancelBtn}
          </div>
        </div>
      );
    }

    if (cuff.status === 'error') {
      return (
        <div className="measurement-prompt-card">
          <p className="measurement-prompt-title">{t('vitalsErrorTitle')}</p>
          <p className="error-text">{t(cuff.errorKey ?? 'vitalsErrGeneric')}</p>
          <div className="measurement-card-actions">
            <button
              type="button"
              className="primary-btn"
              onClick={() => void cuff.startWatching(true)}
            >
              {t('vitalsRetry')}
            </button>
            <button
              type="button"
              className="secondary-btn"
              onClick={() => {
                cuff.reset();
                setSbpChoice('manual');
              }}
            >
              {t('vitalsEnterManually')}
            </button>
            {cancelBtn}
          </div>
        </div>
      );
    }

    if (cuff.reading) {
      return (
        <div className="measurement-prompt-card">
          <p className="measurement-prompt-title">{t('vitalsMeasureTitle')}</p>
          {cuff.reading.measured_at && (
            <p className="measurement-prompt-subtitle muted">
              {t('vitalsMeasuredAt', { time: new Date(cuff.reading.measured_at).toLocaleTimeString() })}
            </p>
          )}
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
                disabled={busy}
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
                disabled={busy}
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
                disabled={busy}
              />
            </label>
          </div>
          {errorNote}
          <div className="measurement-card-actions">
            <button
              type="button"
              className="primary-btn"
              onClick={() => void submitSbp('device')}
              disabled={busy || !systolic.trim() || !diastolic.trim()}
            >
              {saving ? t('loading') : t('measurementConfirm')}
            </button>
            <button type="button" className="text-btn location-prompt-skip" onClick={() => cuff.reset()}>
              {t('vitalsMeasureAgain')}
            </button>
            {cancelBtn}
          </div>
        </div>
      );
    }

    // Machine chosen, watch not started yet — show cuff instructions.
    return (
      <div className="measurement-prompt-card">
        <p className="measurement-prompt-title">{t('vitalsMeasureTitle')}</p>
        <ol className="vitals-steps">
          <li>{t('vitalsStep1')}</li>
          <li>{t('vitalsStep2')}</li>
          <li>{t('vitalsStep3')}</li>
        </ol>
        <div className="measurement-card-actions">
          <button
            type="button"
            className="primary-btn"
            onClick={() => void cuff.startWatching()}
            disabled={busy}
          >
            {t('vitalsReadyButton')}
          </button>
          <button
            type="button"
            className="text-btn location-prompt-skip"
            onClick={() => setSbpChoice('unset')}
            disabled={busy}
          >
            {t('vitalsBack')}
          </button>
          {cancelBtn}
        </div>
      </div>
    );
  }

  if (vital === 'weight') {
    return (
      <div className="measurement-prompt-card">
        <p className="measurement-prompt-title">{t('measurementWeightTitle')}</p>
        <p className="measurement-prompt-subtitle muted">{t('measurementWeightHint')}</p>
        <div className="vitals-form-grid cols-2">
          <label className="vitals-extra-field">
            <span>{t('vitalsWeight')}</span>
            <input
              type="number"
              inputMode="decimal"
              min={1}
              max={400}
              step={0.1}
              value={weightKg}
              onChange={(e) => setWeightKg(e.target.value)}
              disabled={busy}
              autoFocus
            />
          </label>
          <label className="vitals-extra-field">
            <span>{t('vitalsHeight')}</span>
            <input
              type="number"
              inputMode="decimal"
              min={1}
              max={272}
              step={0.1}
              value={heightCm}
              onChange={(e) => setHeightCm(e.target.value)}
              disabled={busy}
            />
          </label>
        </div>
        {errorNote}
        <div className="measurement-card-actions">
          <button
            type="button"
            className="primary-btn"
            onClick={() => void submitWeight()}
            disabled={busy || !weightKg.trim() || !heightCm.trim()}
          >
            {saving ? t('loading') : t('measurementConfirm')}
          </button>
          {cancelBtn}
        </div>
      </div>
    );
  }

  return null;
}
