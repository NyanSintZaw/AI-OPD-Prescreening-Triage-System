import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
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
  onCancel?: () => void;
  disabled?: boolean;
}

type SbpChoice = 'unset' | 'machine' | 'manual';

const parseNum = (v: string): number | undefined => {
  const n = Number.parseFloat(v);
  return Number.isFinite(n) ? n : undefined;
};

/**
 * Inline card the booth shows mid-interview when the screening engine asks
 * for a reading it needs right now (``awaiting_measurement`` on chat turns,
 * the ``measurement_request`` frame on voice calls). Handles the three
 * vitals the engine can request: temperature, blood pressure (machine or
 * manual), and weight+height together.
 */
export function MeasurementCard({ vital, onSubmit, onCancel, disabled }: MeasurementCardProps) {
  const { t } = useTranslation();
  const { sessionId } = useSessionStorage();
  const [saving, setSaving] = useState(false);
  const [errorKey, setErrorKey] = useState<string | null>(null);

  const [tempValue, setTempValue] = useState('');

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
    setTempValue('');
    setSbpChoice('unset');
    setSystolic('');
    setDiastolic('');
    setPulse('');
    setWeightKg('');
    setHeightCm('');
    cuff.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vital]);

  // The cuff hook resolved a reading — auto-fill the (still editable)
  // fields, same as the pre-conversation vitals gate used to.
  useEffect(() => {
    if (!cuff.reading) return;
    if (cuff.reading.systolic != null) setSystolic(String(cuff.reading.systolic));
    if (cuff.reading.diastolic != null) setDiastolic(String(cuff.reading.diastolic));
    if (cuff.reading.pulse_bpm != null) setPulse(String(cuff.reading.pulse_bpm));
  }, [cuff.reading]);

  const busy = saving || Boolean(disabled);

  const submitTemp = async () => {
    const value = parseNum(tempValue);
    if (value === undefined || value < 30 || value > 45) {
      setErrorKey('vitalsRequiredError');
      return;
    }
    setSaving(true);
    setErrorKey(null);
    try {
      if (sessionId) {
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
        await api.updateSessionVitals(sessionId, {
          systolic: sys,
          diastolic: dia,
          pulse_bpm: pul,
          measured_at: fromDevice ? cuff.reading?.measured_at ?? undefined : undefined,
          source: fromDevice ? 'device' : 'manual',
          reading_id: fromDevice ? cuff.reading?.reading_id ?? undefined : undefined,
        });
      }
    } catch {
      // Non-fatal: the conversation can continue without the write-back.
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
    setSaving(true);
    setErrorKey(null);
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

  const cancelBtn = onCancel && (
    <button type="button" className="text-btn location-prompt-skip" onClick={onCancel} disabled={busy}>
      {t('measurementCancel')}
    </button>
  );

  // Patient declines the reading (cuff busy, in a hurry, …). The question is
  // already marked asked engine-side, so a plain continuation turn moves the
  // interview on without the measurement.
  const skipMeasurement = async () => {
    setErrorKey(null);
    await onSubmit(t('measureSkipPhrase'));
  };
  const skipBtn = (
    <button
      type="button"
      className="text-btn location-prompt-skip"
      onClick={() => void skipMeasurement()}
      disabled={busy}
    >
      {t('measureSkip')}
    </button>
  );

  if (vital === 'temp') {
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
        {errorKey && <p className="error-text">{t(errorKey)}</p>}
      </div>
    );
  }

  if (vital === 'sbp') {
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
            {skipBtn}
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
          {errorKey && <p className="error-text">{t(errorKey)}</p>}
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
          {errorKey && <p className="error-text">{t(errorKey)}</p>}
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
        {errorKey && <p className="error-text">{t(errorKey)}</p>}
        <div className="measurement-card-actions">
          <button
            type="button"
            className="primary-btn"
            onClick={() => void submitWeight()}
            disabled={busy || !weightKg.trim() || !heightCm.trim()}
          >
            {saving ? t('loading') : t('measurementConfirm')}
          </button>
          {skipBtn}
          {cancelBtn}
        </div>
      </div>
    );
  }

  return null;
}
