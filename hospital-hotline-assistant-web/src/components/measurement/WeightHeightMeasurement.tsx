import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../../api';
import type { AppLanguage } from '../../i18n/resources';
import { useSessionStorage } from '../../hooks/useSession';
import { parseNum, useMeasurementValidation } from './shared';

export interface WeightHeightMeasurementProps {
  language?: AppLanguage;
  /** Fired once the values are saved on the session; receives a short
   *  patient-utterance-shaped string the caller should send as the next
   *  conversation turn (e.g. ``"68 kg, 172 cm"``). */
  onSubmit: (continuationText: string) => void | Promise<void>;
  onCancel?: () => void;
  disabled?: boolean;
}

/**
 * Inline card the booth shows when the screening engine asks for weight and
 * height near the end of the interview. The values are self-reported (the
 * patient types what they know) — there is no scale at the booth; when the
 * HIS holds a recent measurement the engine never asks at all.
 */
export function WeightHeightMeasurement({ language, onSubmit, onCancel, disabled }: WeightHeightMeasurementProps) {
  const { t, i18n } = useTranslation();
  const { sessionId } = useSessionStorage();
  const lang = language ?? (i18n.language === 'en' ? 'en' : 'th');
  const { errorKey, errorText, setErrorKey, accept, rejectCross, clearError } =
    useMeasurementValidation(lang);
  const [saving, setSaving] = useState(false);

  const [weightKg, setWeightKg] = useState('');
  const [heightCm, setHeightCm] = useState('');

  const busy = saving || Boolean(disabled);

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
    clearError();
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
