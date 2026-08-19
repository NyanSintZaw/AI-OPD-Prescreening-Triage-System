import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../../api';
import type { AppLanguage } from '../../i18n/resources';
import { useSessionStorage } from '../../hooks/useSession';
import { parseNum, useMeasurementValidation } from './shared';

export interface PulseOximeterMeasurementProps {
  language?: AppLanguage;
  /** Fired once the reading is saved on the session; receives a short
   *  patient-utterance-shaped string the caller should send as the next
   *  conversation turn (e.g. ``"SpO2 97%, pulse 72 bpm"``). */
  onSubmit: (continuationText: string) => void | Promise<void>;
  onCancel?: () => void;
  disabled?: boolean;
}

/**
 * Inline card for a fingertip SpO2 measurement (Rossmax SB210). Shown when
 * the screening engine asks for SpO2, or when the patient opts in from the
 * conversation ("measure my oxygen"). Device-first — the fetch endpoint
 * merges the settled reading into the session vitals — with a manual-entry
 * fallback for when the device is unavailable.
 */
export function PulseOximeterMeasurement({ language, onSubmit, onCancel, disabled }: PulseOximeterMeasurementProps) {
  const { t, i18n } = useTranslation();
  const { sessionId } = useSessionStorage();
  const lang = language ?? (i18n.language === 'en' ? 'en' : 'th');
  const { errorKey, errorText, setErrorKey, accept, clearError } = useMeasurementValidation(lang);
  const [saving, setSaving] = useState(false);

  const [fetching, setFetching] = useState(false);
  const [manual, setManual] = useState(false);
  const [manualValue, setManualValue] = useState('');
  const [deviceSpo2, setDeviceSpo2] = useState<number | null>(null);
  const [devicePulse, setDevicePulse] = useState<number | null>(null);
  // Set when the patient backs out of a device fetch: the in-flight
  // long-poll result is ignored instead of aborted (kiosk has one station).
  const cancelRef = useRef(false);

  const busy = saving || Boolean(disabled);

  const startDevice = async () => {
    clearError();
    setFetching(true);
    setDeviceSpo2(null);
    setDevicePulse(null);
    cancelRef.current = false;
    try {
      const result = await api.fetchSpo2(sessionId, 45);
      if (cancelRef.current) return;
      if (result.status === 'ok' && result.spo2 != null) {
        setDeviceSpo2(result.spo2);
        setDevicePulse(result.pulse_bpm ?? null);
      } else if (result.status === 'timeout') {
        setErrorKey('measureSpo2DeviceTimeout');
      } else {
        setErrorKey('measureSpo2DeviceError');
      }
    } catch {
      if (!cancelRef.current) setErrorKey('measureSpo2DeviceError');
    } finally {
      if (!cancelRef.current) setFetching(false);
    }
  };

  const confirmDevice = async () => {
    if (deviceSpo2 == null) return;
    // The fetch endpoint already persisted and merged the reading — the
    // continuation turn just carries it into the conversation.
    const text =
      devicePulse != null
        ? `SpO2 ${deviceSpo2}%, pulse ${devicePulse} bpm`
        : `SpO2 ${deviceSpo2}%`;
    await onSubmit(text);
  };

  const submitManual = async () => {
    const value = parseNum(manualValue);
    if (value === undefined) {
      setErrorKey('vitalsRequiredError');
      return;
    }
    if (!accept('spo2', value)) return;
    setSaving(true);
    clearError();
    try {
      if (sessionId) {
        await api.updateSessionMeasurement(sessionId, { vital: 'spo2', value });
      }
    } catch {
      // Non-fatal: the continuation turn's extraction can still pick it up.
    } finally {
      setSaving(false);
    }
    await onSubmit(`SpO2 ${value}%`);
  };

  const errorNote = (errorText || errorKey) && (
    <p className="error-text" role="alert">
      {errorText ? errorText : t(errorKey!)}
    </p>
  );

  const cancelBtn = onCancel && (
    <button type="button" className="text-btn location-prompt-skip" onClick={onCancel} disabled={busy}>
      {t('measurementCancel')}
    </button>
  );

  if (fetching) {
    return (
      <div className="measurement-prompt-card">
        <p className="measurement-prompt-title">{t('measureSpo2Waiting')}</p>
        <p className="measurement-prompt-subtitle muted">{t('measureSpo2WaitingHint')}</p>
        <div className="vitals-progress">
          <div className="vitals-progress-bar" />
        </div>
        <div className="measurement-card-actions">
          <button
            type="button"
            className="text-btn location-prompt-skip"
            onClick={() => {
              cancelRef.current = true;
              setFetching(false);
            }}
          >
            {t('measurementCancel')}
          </button>
        </div>
      </div>
    );
  }

  if (deviceSpo2 != null) {
    return (
      <div className="measurement-prompt-card">
        <p className="measurement-prompt-title">{t('measureSpo2ResultTitle')}</p>
        <div className="bpdev-test-values" style={{ justifyContent: 'center', fontSize: '1.2rem' }}>
          <span>
            SpO₂ <strong>{deviceSpo2}</strong>%
          </span>
          {devicePulse != null && (
            <span>
              <strong>{devicePulse}</strong> bpm
            </span>
          )}
        </div>
        <div className="measurement-card-actions">
          <button
            type="button"
            className="primary-btn"
            onClick={() => void confirmDevice()}
            disabled={busy}
          >
            {t('measurementConfirm')}
          </button>
          <button
            type="button"
            className="text-btn location-prompt-skip"
            onClick={() => void startDevice()}
            disabled={busy}
          >
            {t('vitalsMeasureAgain')}
          </button>
          {cancelBtn}
        </div>
      </div>
    );
  }

  if (manual) {
    return (
      <div className="measurement-prompt-card">
        <p className="measurement-prompt-title">{t('measureSpo2ManualTitle')}</p>
        <div className="location-prompt-row">
          <input
            type="number"
            inputMode="numeric"
            className="location-prompt-input"
            placeholder="97"
            min={50}
            max={100}
            value={manualValue}
            onChange={(e) => setManualValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void submitManual();
            }}
            disabled={busy}
            autoFocus
          />
          <button
            type="button"
            className="primary-btn location-prompt-confirm"
            onClick={() => void submitManual()}
            disabled={busy || !manualValue.trim()}
          >
            {saving ? t('loading') : t('measurementConfirm')}
          </button>
        </div>
        <div className="measurement-card-actions">
          <button
            type="button"
            className="text-btn location-prompt-skip"
            onClick={() => setManual(false)}
            disabled={busy}
          >
            {t('vitalsBack')}
          </button>
          {cancelBtn}
        </div>
        {errorNote}
      </div>
    );
  }

  return (
    <div className="measurement-prompt-card">
      <p className="measurement-prompt-title">{t('measureSpo2Title')}</p>
      <p className="measurement-prompt-subtitle muted">{t('measureSpo2Hint')}</p>
      <div className="measurement-card-actions">
        <button
          type="button"
          className="primary-btn"
          onClick={() => void startDevice()}
          disabled={busy}
        >
          {t('measureSpo2Start')}
        </button>
        <button
          type="button"
          className="text-btn location-prompt-skip"
          onClick={() => setManual(true)}
          disabled={busy}
        >
          {t('vitalsEnterManually')}
        </button>
        {cancelBtn}
      </div>
      {errorNote}
    </div>
  );
}
