import { useEffect, useState } from 'react';
import { ClipboardText } from '@phosphor-icons/react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import { getAdminRole, getAdminToken } from '../api/client';

const POLL_MS = 60_000;

/**
 * Pending-review count for the badge. Polls only while the button is on
 * screen and the tab is visible.
 */
function usePendingReviewCount(enabled: boolean): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let timer: ReturnType<typeof setTimeout>;
    let alive = true;

    const tick = async () => {
      try {
        if (document.visibilityState === 'visible') {
          const { pending } = await api.getPendingReviewCount();
          if (alive) setCount(pending);
        }
      } catch {
        /* keep the last-known count — a badge must never break the page */
      } finally {
        if (alive) timer = setTimeout(tick, POLL_MS);
      }
    };

    void tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [enabled]);

  return count;
}

/**
 * Fixed shortcut to the nurse portal's Triage Reviews list.
 *
 * Nurse portal only. It used to render on /admin too, which put a button that
 * jumps to another portal on top of every administrator's screen — the admin
 * surfaces are for inspecting how the booth ran, and confirming an individual
 * case is not their job. It stays on the nurse's own non-review tabs, where it
 * is a shortcut back to their queue rather than a trip somewhere else. The tab
 * is read from ?tab=, so the click switches tabs in place.
 */
export function ReviewsFab() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();

  // Nurse portal only, and hidden on the destination itself — reviews is the
  // default tab, so a missing or unknown ?tab= counts as reviews. Resolved
  // before the poll hook so the hook order never changes between renders, and
  // so the admin portal never opens the polling request at all.
  const onNurse = location.pathname.startsWith('/nurse');
  const tab = new URLSearchParams(location.search).get('tab');
  const visible = Boolean(getAdminToken() && getAdminRole()) && onNurse && tab === 'schedules';

  const pending = usePendingReviewCount(visible);

  if (!visible) return null;

  return (
    <button
      type="button"
      className={`reviews-fab ${pending > 0 ? 'has-pending' : ''}`}
      onClick={() => navigate('/nurse?tab=reviews')}
      // The count belongs in the name; the badge below is aria-hidden so
      // screen readers don't read it twice.
      aria-label={pending > 0 ? `${t('reviewsFabLabel')} (${pending})` : t('reviewsFabLabel')}
      title={t('reviewsFabLabel')}
    >
      <span className="reviews-fab-icon" aria-hidden="true">
        <ClipboardText size={24} weight="fill" />
      </span>
      <span className="reviews-fab-label">{t('reviewsFabShort')}</span>
      {pending > 0 && (
        <span className="reviews-fab-badge" aria-hidden="true">
          {pending > 99 ? '99+' : pending}
        </span>
      )}
    </button>
  );
}
