import { cx } from './cx';

export interface StepperProps {
  steps: string[];
  /** 0-based index of the current step. */
  current: number;
  /** `kiosk` = larger, centred, for the booth header. */
  size?: 'md' | 'kiosk';
}
/** Linear progress through the kiosk flow. The current step is the one gold element on screen. */
export function Stepper({ steps, current, size = 'md' }: StepperProps) {
  return (
    <ol className={cx('mali-stepper', `mali-stepper--${size}`)} aria-label="Progress">
      {steps.map((s, i) => (
        <li key={s} className={cx('mali-step', i < current && 'mali-step--done', i === current && 'mali-step--current')}
          aria-current={i === current ? 'step' : undefined}>
          <span className="mali-step__dot" aria-hidden="true">{i < current ? '✓' : i + 1}</span>
          <span className="mali-step__label">{s}</span>
        </li>
      ))}
    </ol>
  );
}
