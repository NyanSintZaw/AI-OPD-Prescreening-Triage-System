import { useTranslation } from 'react-i18next';
import type { ChatAssessment } from '../hooks/useChat';

interface RecommendationCardProps {
  assessment: ChatAssessment;
}

export function RecommendationCard({ assessment }: RecommendationCardProps) {
  const { t } = useTranslation();
  const redFlags = assessment.symptoms?.redFlags ?? [];

  if (!assessment.severity && !assessment.department) {
    return null;
  }

  return (
    <div className="recommendation-card">
      <h3>{t('recommendationTitle')}</h3>
      {assessment.severity && (
        <p>
          <strong>{t('severity')}:</strong>{' '}
          <span className={`severity-badge severity-${assessment.severity.level}`}>
            {t(`severity_${assessment.severity.level}`)}
          </span>
          {assessment.severity.explanation && (
            <span className="recommendation-detail"> — {assessment.severity.explanation}</span>
          )}
        </p>
      )}
      {assessment.symptoms?.painScore !== undefined && (
        <p>
          <strong>{t('painScore')}:</strong> {assessment.symptoms.painScore}/10
          {assessment.symptoms.painLocation && (
            <span className="recommendation-detail">
              {' '}
              — {assessment.symptoms.painLocation}
            </span>
          )}
        </p>
      )}
      {assessment.symptoms?.distressScore !== undefined && (
        <p>
          <strong>{t('distressScore')}:</strong>{' '}
          {assessment.symptoms.distressScore}/10
          {assessment.symptoms.distressType && (
            <span className="recommendation-detail">
              {' '}
              — {assessment.symptoms.distressType}
            </span>
          )}
        </p>
      )}
      {redFlags.length > 0 && (
        <p>
          <strong>{t('redFlags')}:</strong> {redFlags.join(', ')}
        </p>
      )}
      {assessment.department && (
        <p>
          <strong>{t('department')}:</strong>{' '}
          {assessment.department.name ?? assessment.department.departmentId}
          {assessment.department.reason && (
            <span className="recommendation-detail"> — {assessment.department.reason}</span>
          )}
        </p>
      )}
    </div>
  );
}
