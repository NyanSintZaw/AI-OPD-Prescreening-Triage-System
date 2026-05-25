import { useTranslation } from 'react-i18next';

interface EmergencyBannerProps {
  message: string;
  ctaLabel?: string;
  onCtaClick?: () => void;
}

export function EmergencyBanner({ message, ctaLabel, onCtaClick }: EmergencyBannerProps) {
  const { t } = useTranslation();

  return (
    <div className="emergency-banner" role="alert">
      <strong>{t('emergencyTitle')}</strong>
      <p>{message}</p>
      {ctaLabel && onCtaClick && (
        <button type="button" className="emergency-cta-btn" onClick={onCtaClick}>
          {ctaLabel}
        </button>
      )}
    </div>
  );
}
