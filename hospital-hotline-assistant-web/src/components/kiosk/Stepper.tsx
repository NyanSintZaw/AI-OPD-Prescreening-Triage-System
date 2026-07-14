import { Fragment } from 'react';
import { useTranslation } from 'react-i18next';
import { Check } from '@phosphor-icons/react';

export type KioskStep = 0 | 1 | 2;

/**
 * The 3-step session progress indicator shown in the top bar:
 * Identify → Symptoms → Result. Purely presentational.
 */
export function Stepper({ current }: { current: KioskStep }) {
  const { t } = useTranslation();
  const steps = [t('kioskStepIdentify'), t('kioskStepTalk'), t('kioskStepResult')];

  return (
    <nav className="k-stepper" aria-label="progress">
      {steps.map((label, i) => {
        const state = i < current ? 'done' : i === current ? 'current' : '';
        return (
          <Fragment key={label}>
            {i > 0 && <span className="k-step-line" aria-hidden="true" />}
            <span className={`k-step ${state}`}>
              <span className="k-step-dot" aria-hidden="true">
                {i < current ? <Check size={18} weight="bold" /> : i + 1}
              </span>
              <span className="k-step-label">{label}</span>
            </span>
          </Fragment>
        );
      })}
    </nav>
  );
}
