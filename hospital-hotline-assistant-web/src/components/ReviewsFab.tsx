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
// ponytail: counts by fetching the pending rows themselves (LIMIT 200, fat
// joins). Add GET /admin/reviews/pending-count if this poll ever shows up in
// the logs.
function usePendingReviewCount(enabled: boolean): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let timer: ReturnType<typeof setTimeout>;
    let alive = true;

    const tick = async () => {
      try {
        if (document.visibilityState === 'visible') {
          const rows = await api.listAssessmentReviews('pending');
          if (alive) setCount(rows.length);
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
 * Fixed shortcut that jumps any staff screen to the nurse portal's Triage
 * Reviews list. Rendered by Layout, so every /admin and /nurse tab gets it
 * without opting in. The nurse tab is read from ?tab=, so the same click
 * works whether it navigates across routes or only switches tabs in place.
 * Nudges and shows a count while cases are waiting to be reviewed.
 */
export function ReviewsFab() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();

  // Staff-only, and hidden on the destination itself — reviews is the default
  // tab, so a missing or unknown ?tab= counts as reviews. Resolved before the
  // poll hook so the hook order never changes between renders.
  const onNurse = location.pathname.startsWith('/nurse');
  const tab = new URLSearchParams(location.search).get('tab');
  const visible = Boolean(getAdminToken() && getAdminRole()) && (!onNurse || tab === 'schedules');

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
