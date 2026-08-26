import { useTranslation } from 'react-i18next';

/**
 * The engine's MOPH level. The number is not decoration: levels 1 and 2 sit
 * at ΔE 13 for normal colour vision, so the colour alone cannot carry which
 * one this is. Colour reinforces, the digit states.
 *
 * Shared by the nurse queue and the admin session log — one badge, so the
 * rule above can never hold in one portal and lapse in the other.
 */
export function TriageBadge({ level, size = 'md' }: { level?: number | null; size?: 'md' | 'lg' }) {
  const { t } = useTranslation();
  if (!level) {
    return <span className={`triage-badge triage-badge-none triage-badge-${size}`}>—</span>;
  }
  return (
    <span
      className={`triage-badge triage-level-${level} triage-badge-${size}`}
      title={t(`triageLevelName_${level}`)}
    >
      <span className="triage-badge-num">{level}</span>
      {size === 'lg' ? (
        <span className="triage-badge-name">{t(`triageLevelName_${level}`)}</span>
      ) : null}
    </span>
  );
}
