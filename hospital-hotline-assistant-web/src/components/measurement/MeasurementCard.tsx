import type { AppLanguage } from '../../i18n/resources';
import { BloodPressureMeasurement } from './BloodPressureMeasurement';
import { PulseOximeterMeasurement } from './PulseOximeterMeasurement';
import { TemperatureMeasurement } from './TemperatureMeasurement';
import { WeightHeightMeasurement } from './WeightHeightMeasurement';

export interface MeasurementCardProps {
  /** Vital the screening engine is asking the booth to measure right now
   *  (``'temp' | 'sbp' | 'weight' | 'spo2'`` — see ``VitalName`` on the backend). */
  vital: string;
  language?: AppLanguage;
  /** Fired once the reading is saved on the session; receives a short
   *  patient-utterance-shaped string the caller should send as the next
   *  conversation turn (e.g. ``"37.2 °C"``, ``"BP 118/76"``). */
  onSubmit: (continuationText: string) => void | Promise<void>;
  /** BP only — see BloodPressureMeasurement.onRest. */
  onRest?: (secondsRemaining: number) => void;
  onCancel?: () => void;
  disabled?: boolean;
}

/**
 * Dispatcher for the mid-interview measurement cards (``awaiting_measurement``
 * on chat turns, the ``measurement_request`` frame on voice calls). Each
 * device has its own component; the ``key`` remounts it whenever the engine
 * asks for a different vital, resetting all entry state.
 *
 * Measurements the engine asks for are required (it only asks when the
 * interview needs them) — there is deliberately no skip control.
 */
export function MeasurementCard({ vital, language, onSubmit, onRest, onCancel, disabled }: MeasurementCardProps) {
  if (vital === 'temp') {
    return (
      <TemperatureMeasurement
        key={vital}
        language={language}
        onSubmit={onSubmit}
        onCancel={onCancel}
        disabled={disabled}
      />
    );
  }
  if (vital === 'sbp') {
    return (
      <BloodPressureMeasurement
        key={vital}
        language={language}
        onSubmit={onSubmit}
        onRest={onRest}
        onCancel={onCancel}
        disabled={disabled}
      />
    );
  }
  if (vital === 'weight') {
    return (
      <WeightHeightMeasurement
        key={vital}
        language={language}
        onSubmit={onSubmit}
        onCancel={onCancel}
        disabled={disabled}
      />
    );
  }
  if (vital === 'spo2') {
    return (
      <PulseOximeterMeasurement
        key={vital}
        language={language}
        onSubmit={onSubmit}
        onCancel={onCancel}
        disabled={disabled}
      />
    );
  }
  return null;
}
