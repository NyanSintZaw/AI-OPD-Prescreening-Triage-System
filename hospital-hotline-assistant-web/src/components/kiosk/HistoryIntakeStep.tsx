import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { motion } from 'framer-motion';

export interface HistoryIntakeValues {
  smoking_alcohol: string;
  allergies: string;
  chronic_conditions: string;
  past_surgeries: string;
  family_history: string;
}

interface HistoryIntakeStepProps {
  busy?: boolean;
  error?: boolean;
  onSubmit: (values: HistoryIntakeValues) => void;
  onSkip: () => void;
}

const EMPTY: HistoryIntakeValues = {
  smoking_alcohol: '',
  allergies: '',
  chronic_conditions: '',
  past_surgeries: '',
  family_history: '',
};

/**
 * First-time patient structured history (smoking/alcohol, allergies,
 * chronic conditions, surgeries, family history) before the symptom interview.
 */
export function HistoryIntakeStep({
  busy = false,
  error = false,
  onSubmit,
  onSkip,
}: HistoryIntakeStepProps) {
  const { t } = useTranslation();
  const [values, setValues] = useState<HistoryIntakeValues>(EMPTY);

  const setField = (key: keyof HistoryIntakeValues, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  const fields: Array<{ key: keyof HistoryIntakeValues; labelKey: string; placeholderKey: string }> = [
    {
      key: 'smoking_alcohol',
      labelKey: 'kioskHistorySmokingAlcohol',
      placeholderKey: 'kioskHistorySmokingAlcoholPh',
    },
    {
      key: 'allergies',
      labelKey: 'kioskHistoryAllergies',
      placeholderKey: 'kioskHistoryAllergiesPh',
    },
    {
      key: 'chronic_conditions',
      labelKey: 'kioskHistoryChronic',
      placeholderKey: 'kioskHistoryChronicPh',
    },
    {
      key: 'past_surgeries',
      labelKey: 'kioskHistorySurgeries',
      placeholderKey: 'kioskHistorySurgeriesPh',
    },
    {
      key: 'family_history',
      labelKey: 'kioskHistoryFamily',
      placeholderKey: 'kioskHistoryFamilyPh',
    },
  ];

  return (
    <motion.div
      className="k-hello"
      initial={{ opacity: 0, scale: 0.96 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.3, ease: 'easeOut' }}
      style={{ width: '100%', maxWidth: 640, margin: '0 auto', textAlign: 'left' }}
    >
      <h2 className="k-hello-name" style={{ textAlign: 'center' }}>
        {t('kioskHistoryTitle')}
      </h2>
      <p className="k-hello-lead" style={{ textAlign: 'center' }}>
        {t('kioskHistoryLead')}
      </p>

      <div style={{ display: 'grid', gap: 14, width: '100%', marginTop: 8 }}>
        {fields.map((field) => (
          <label key={field.key} style={{ display: 'grid', gap: 6 }}>
            <span style={{ fontWeight: 600, fontSize: 15 }}>{t(field.labelKey)}</span>
            <input
              type="text"
              value={values[field.key]}
              disabled={busy}
              placeholder={t(field.placeholderKey)}
              onChange={(e) => setField(field.key, e.target.value)}
              className="k-display"
              style={{
                fontSize: 16,
                textAlign: 'left',
                padding: '12px 14px',
                minHeight: 48,
              }}
              autoComplete="off"
            />
          </label>
        ))}
      </div>

      {error && (
        <p className="k-error" style={{ marginTop: 12 }}>
          {t('kioskHistoryError')}
        </p>
      )}

      <div
        style={{
          display: 'flex',
          gap: 12,
          justifyContent: 'center',
          flexWrap: 'wrap',
          marginTop: 20,
          width: '100%',
        }}
      >
        <button
          type="button"
          className="k-btn primary xl"
          disabled={busy}
          onClick={() => onSubmit(values)}
          style={{ minWidth: 160 }}
        >
          {busy ? t('loading') : t('kioskHistorySave')}
        </button>
        <button
          type="button"
          className="k-textlink"
          disabled={busy}
          onClick={onSkip}
        >
          {t('kioskHistorySkip')}
        </button>
      </div>
    </motion.div>
  );
}
