import { useTranslation } from 'react-i18next';
import { CheckCircle } from '@phosphor-icons/react';

/**
 * How current the list is, and a visible confirmation when it was just made so.
 *
 * Two constraints pull against each other here and both are load-bearing:
 *
 *  - It has to be **noticed**. A refreshed board very often looks identical to
 *    the one before it — nothing arrived in the last thirty seconds — so the
 *    press needs an answer that is not "the numbers you were already reading".
 *    A quiet colour shift on 12px text was not enough.
 *  - It must **not move anything**. The first version of this was a notice that
 *    appeared beside the refresh button and shoved that button 167px sideways
 *    on every press, so the control jumped out from under the cursor that had
 *    just clicked it, then jumped back three seconds later.
 *
 * So the confirmation is painted, never inserted. The pill's padding is
 * cancelled by an equal negative margin, which lets it grow visually while its
 * layout box stays exactly the size of the text; the tick is always in the DOM
 * and only changes opacity. Nothing mounts, nothing reflows, and the whole
 * thing is still unmistakable.
 */
export function Freshness({ at, fresh }: { at: Date | null; fresh: boolean }) {
  const { t } = useTranslation();
  if (!at) return null;
  return (
    <span className="freshness" data-fresh={fresh || undefined}>
      <CheckCircle className="freshness-tick" size={14} weight="fill" aria-hidden="true" />
      {t('nurseRefreshedAt', {
        time: at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      })}
    </span>
  );
}
