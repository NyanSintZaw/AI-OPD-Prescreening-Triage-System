import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../../api';
import type { AppLanguage } from '../../i18n/resources';
import { useBpCuffWatch } from '../../hooks/useBpCuffWatch';
import { useSessionStorage } from '../../hooks/useSession';
import { parseNum, useMeasurementValidation } from './shared';

export interface BloodPressureMeasurementProps {
  language?: AppLanguage;
  /** Fired once the reading is saved on the session; receives a short
   *  patient-utterance-shaped string the caller should send as the next
   *  conversation turn (e.g. ``"BP 118/76"``). */
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

/**
 * Inline card the booth shows when the screening engine asks for a blood
 * pressure mid-interview: Omron cuff watch, or manual entry, plus the
 * hypertensive-crisis rest window.
 */
export function BloodPressureMeasurement({ language, onSubmit, onRest, onCancel, disabled }: BloodPressureMeasurementProps) {
  const { t, i18n } = useTranslation();
  const { sessionId } = useSessionStorage();
  const lang = language ?? (i18n.language === 'en' ? 'en' : 'th');
  const { errorKey, errorText, setErrorKey, accept, rejectCross } =
    useMeasurementValidation(lang);
  const [saving, setSaving] = useState(false);
  const [restSeconds, setRestSeconds] = useState<number | null>(null);

  const [sbpChoice, setSbpChoice] = useState<SbpChoice>('unset');
  const [systolic, setSystolic] = useState('');
  const [diastolic, setDiastolic] = useState('');
  const [pulse, setPulse] = useState('');
  const cuff = useBpCuffWatch(sessionId);

  // Poll rest status so a crisis timer from an earlier reading (possibly in
  // a prior kiosk visit for the same HN) blocks remeasure.
  useEffect(() => {
    if (!sessionId) return;
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // The cuff hook resolved a reading — auto-fill the (still editable)
  // fields, same as the pre-conversation vitals gate used to.
  useEffect(() => {
    if (!cuff.reading) return;
    if (cuff.reading.systolic != null) setSystolic(String(cuff.reading.systolic));
    if (cuff.reading.diastolic != null) setDiastolic(String(cuff.reading.diastolic));
    if (cuff.reading.pulse_bpm != null) setPulse(String(cuff.reading.pulse_bpm));
  }, [cuff.reading]);

  const busy = saving || Boolean(disabled) || (restSeconds != null && restSeconds > 0);

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
