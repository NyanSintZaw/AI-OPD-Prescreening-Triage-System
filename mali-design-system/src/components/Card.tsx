import type { HTMLAttributes, ReactNode } from 'react';
import { cx } from './cx';

export interface CardProps extends Omit<HTMLAttributes<HTMLElement>, 'title'> {
  /** Optional heading row. */
  title?: ReactNode;
  /** Right side of the heading row (actions, a Badge). */
  aside?: ReactNode;
  /** `flat` = hairline only, `raised` = soft tinted shadow. Default flat. */
  elevation?: 'flat' | 'raised';
  padding?: 'none' | 'md' | 'lg';
}
/** A hairline container. Never nest cards. */
export function Card({ title, aside, elevation = 'flat', padding = 'md', className, children, ...rest }: CardProps) {
  return (
    <section className={cx('mali-card', `mali-card--${elevation}`, `mali-card--pad-${padding}`, className)} {...rest}>
      {(title || aside) && <header className="mali-card__head"><h3 className="mali-card__title">{title}</h3>{aside}</header>}
      {children}
    </section>
  );
}
