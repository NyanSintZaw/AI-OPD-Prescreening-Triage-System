import type { Icon } from '@phosphor-icons/react';

export interface StaffNavItem<T extends string> {
  id: T;
  label: string;
  icon: Icon;
  /** Live count rendered beside the label (pending work). Hidden at 0 — a
   *  badge showing "0" reads as a state to clear, not as an empty queue. */
  badge?: number;
}

interface StaffNavProps<T extends string> {
  items: ReadonlyArray<StaffNavItem<T>>;
  active: T;
  onSelect: (id: T) => void;
  /** Portal name, so the sidebar says which of the two portals you are in. */
  title: string;
}

/**
 * The one navigation control for both staff portals.
 *
 * It replaces six separate tab-bar implementations (`.nurse-tab-bar`,
 * `.admin-tab-bar`, `.cm-sec-tabs`, `.portal-tabs`, `.hdb-view-tabs` and the
 * modal bar), which had drifted into two idioms, three indicator widths and
 * an `-active` suffix that matched nothing else.
 */
export function StaffNav<T extends string>({ items, active, onSelect, title }: StaffNavProps<T>) {
  return (
    <nav className="staff-nav" aria-label={title}>
      <p className="staff-nav-title">{title}</p>
      <ul className="staff-nav-list">
        {items.map((item) => {
          const Glyph = item.icon;
          const isActive = item.id === active;
          return (
            <li key={item.id}>
              <button
                type="button"
                className={`staff-nav-item ${isActive ? 'active' : ''}`}
                aria-current={isActive ? 'page' : undefined}
                onClick={() => onSelect(item.id)}
              >
                <Glyph size={20} weight={isActive ? 'fill' : 'regular'} aria-hidden="true" />
                <span className="staff-nav-label">{item.label}</span>
                {item.badge ? <span className="staff-nav-badge">{item.badge}</span> : null}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
