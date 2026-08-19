import { useEffect, useState } from 'react';
import { api } from '../../api';
import type { VitalBoundsOut } from '../../api/types';
import type { AppLanguage } from '../../i18n/resources';

export const parseNum = (v: string): number | undefined => {
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
export const FALLBACK_BOUNDS: Record<string, { min: number; max: number }> = {
  sbp: { min: 50, max: 300 },
  dbp: { min: 20, max: 200 },
  hr: { min: 20, max: 250 },
  temp: { min: 30, max: 45 },
  weight: { min: 1, max: 400 },
  height: { min: 30, max: 272 },
};

/**
 * Shared plausibility-check state for the measurement cards: fetches the
 * authored bounds once, and exposes `accept`/`rejectCross` which set the
 * nurse-authored rejection wording (falling back to the generic i18n key).
 */
export function useMeasurementValidation(lang: AppLanguage) {
  const [bounds, setBounds] = useState<VitalBoundsOut | null>(null);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  // Nurse-authored rejection wording from the criteria; takes precedence over
  // the generic errorKey message when set.
  const [errorText, setErrorText] = useState<string | null>(null);

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

  const clearError = () => {
    setErrorKey(null);
    setErrorText(null);
  };

  return { errorKey, errorText, setErrorKey, setErrorText, accept, rejectCross, clearError };
}
