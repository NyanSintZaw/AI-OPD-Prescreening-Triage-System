import { forwardRef, type InputHTMLAttributes, type SelectHTMLAttributes, type TextareaHTMLAttributes, type ReactNode } from 'react';
import { cx } from './cx';

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  /** Marks the control invalid (red border, aria-invalid). */
  invalid?: boolean;
  /** `kiosk` = 64px tall, 22px text. */
  size?: 'md' | 'kiosk';
}
export const Input = forwardRef<HTMLInputElement, InputProps>(function Input({ invalid, size = 'md', className, ...rest }, ref) {
  return <input ref={ref} aria-invalid={invalid || undefined} className={cx('mali-input', `mali-input--${size}`, className)} {...rest} />;
});

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> { invalid?: boolean; }
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea({ invalid, className, ...rest }, ref) {
  return <textarea ref={ref} aria-invalid={invalid || undefined} className={cx('mali-input', 'mali-textarea', className)} {...rest} />;
});

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> { invalid?: boolean; }
export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select({ invalid, className, children, ...rest }, ref) {
  return (
    <span className="mali-select">
      <select ref={ref} aria-invalid={invalid || undefined} className={cx('mali-input', className)} {...rest}>{children}</select>
    </span>
  );
});

export interface FieldProps {
  label: string;
  /** Control id — wired to the label's htmlFor. */
  htmlFor?: string;
  hint?: string;
  /** Error text; when set the hint is replaced and the control should get `invalid`. */
  error?: string;
  required?: boolean;
  children: ReactNode;
}
/** Label above, control, then hint or error. Errors name the problem and the fix. */
export function Field({ label, htmlFor, hint, error, required, children }: FieldProps) {
  return (
    <div className={cx('mali-field', error && 'mali-field--error')}>
      <label className="mali-field__label" htmlFor={htmlFor}>{label}{required && <span className="mali-field__req"> *</span>}</label>
      {children}
      {(error || hint) && <div className={cx('mali-field__msg', error && 'mali-field__msg--error')} role={error ? 'alert' : undefined}>{error || hint}</div>}
    </div>
  );
}
