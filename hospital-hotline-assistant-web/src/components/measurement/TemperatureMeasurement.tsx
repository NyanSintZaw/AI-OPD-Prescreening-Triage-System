import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../../api';
import type { AppLanguage } from '../../i18n/resources';
import { useSessionStorage } from '../../hooks/useSession';
import { parseNum, useMeasurementValidation } from './shared';

export interface TemperatureMeasurementProps {
  language?: AppLanguage;
  /** Fired once the reading is saved on the session; receives a short
   *  patient-utterance-shaped string the caller should send as the next
   *  conversation turn (e.g. ``"37.2 °C"``). */
  onSubmit: (continuationText: string) => void | Promise<void>;
  onCancel?: () => void;
  disabled?: boolean;
}

/**
 * Inline card the booth shows when the screening engine asks for a
 * temperature mid-interview: BLE thermometer fetch, or manual entry.
 */
export function TemperatureMeasurement({ language, onSubmit, onCancel, disabled }: TemperatureMeasurementProps) {
  const { t, i18n } = useTranslation();
  const { sessionId } = useSessionStorage();
  const lang = language ?? (i18n.language === 'en' ? 'en' : 'th');
  const { errorKey, errorText, setErrorKey, accept, clearError } = useMeasurementValidation(lang);
  const [saving, setSaving] = useState(false);

  const [tempValue, setTempValue] = useState('');
  const [tempFetching, setTempFetching] = useState(false);
  const [deviceTemp, setDeviceTemp] = useState<number | null>(null);
  // Set when the patient backs out of a device fetch: the in-flight
  // long-poll result is ignored instead of aborted (kiosk has one station).
  const tempCancelRef = useRef(false);

  const busy = saving || Boolean(disabled);

  const startTempDevice = async () => {
    clearError();
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
    clearError();
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
