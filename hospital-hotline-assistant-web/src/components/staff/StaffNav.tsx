import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CaretLeft, type Icon } from '@phosphor-icons/react';

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

const COLLAPSE_KEY = 'staff-nav-collapsed';

/**
 * The one navigation control for both staff portals.
 *
 * It replaces six separate tab-bar implementations (`.nurse-tab-bar`,
 * `.admin-tab-bar`, `.cm-sec-tabs`, `.portal-tabs`, `.hdb-view-tabs` and the
 * modal bar), which had drifted into two idioms, three indicator widths and
 * an `-active` suffix that matched nothing else.
 *
 * Collapses to icons only. The choice is per-browser and sticky, because a
 * nurse who wants the widest possible queue table wants it on every shift,
 * not once.
 */
export function StaffNav<T extends string>({ items, active, onSelect, title }: StaffNavProps<T>) {
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === '1';
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0');
    } catch {
      /* private mode — the nav still works, it just will not remember */
    }
  }, [collapsed]);

  return (
    <aside className={`staff-nav ${collapsed ? 'is-collapsed' : ''}`}>
      <div className="staff-nav-head">
        {!collapsed && <p className="staff-nav-title">{title}</p>}
        <button
          type="button"
          className="staff-nav-collapse"
          onClick={() => setCollapsed((v) => !v)}
          aria-expanded={!collapsed}
          aria-label={collapsed ? t('navExpand') : t('navCollapse')}
          title={collapsed ? t('navExpand') : t('navCollapse')}
        >
          <CaretLeft size={16} weight="bold" aria-hidden="true" />
        </button>
      </div>
      <nav aria-label={title}>
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
                  // The label is the only thing identifying the item once the
                  // nav is collapsed, so it has to survive as a tooltip.
                  title={collapsed ? item.label : undefined}
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
    </aside>
  );
}
