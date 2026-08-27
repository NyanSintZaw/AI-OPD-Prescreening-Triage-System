import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { cx } from './cx';
import { Spinner } from './Spinner';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** `primary` is near-black ink on paper — one colour, hierarchy by weight. */
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  /** `kiosk` = 64px hit target, 22px text for the booth. */
  size?: 'sm' | 'md' | 'lg' | 'kiosk';
  /** Replaces the label with a spinner and disables the button. */
  loading?: boolean;
  /** Stretch to the container width. */
  block?: boolean;
  leadingIcon?: ReactNode;
  trailingIcon?: ReactNode;
}

/** Press feedback is scale(.97) over 140ms — never a colour flash. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', size = 'md', loading, block, leadingIcon, trailingIcon, className, children, disabled, ...rest }, ref) {
  return (
    <button ref={ref} type="button" disabled={disabled || loading} data-loading={loading || undefined}
      className={cx('mali-btn', `mali-btn--${variant}`, `mali-btn--${size}`, block && 'mali-btn--block', className)} {...rest}>
      {loading ? <Spinner size={size === 'sm' ? 14 : 18} /> : leadingIcon}
      <span className="mali-btn__label">{children}</span>
      {!loading && trailingIcon}
    </button>
  );
});
