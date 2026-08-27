import { useTranslation } from 'react-i18next';

/**
 * Elapsed minutes as something a human reads at a glance.
 *
 * A raw minute count stops being legible somewhere around an hour — the queue
 * was rendering a three-day-old row as "5298 นาที" — so this steps up to
 * hours and then days.
 */
export function useDuration() {
  const { t } = useTranslation();
  return (minutes: number | null | undefined): string => {
    if (minutes === null || minutes === undefined) return '—';
    if (minutes < 60) return t('dashMinutesShort', { n: minutes });
    const hours = Math.floor(minutes / 60);
    if (hours < 24) {
      const rest = minutes % 60;
      return rest
        ? t('dashHoursMinutesShort', { h: hours, m: rest })
        : t('dashHoursShort', { h: hours });
    }
    const days = Math.floor(hours / 24);
    const restHours = hours % 24;
    return restHours
      ? t('dashDaysHoursShort', { d: days, h: restHours })
      : t('dashDaysShort', { d: days });
  };
}
