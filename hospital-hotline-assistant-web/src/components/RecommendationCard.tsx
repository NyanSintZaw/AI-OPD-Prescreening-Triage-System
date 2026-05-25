import { useTranslation } from 'react-i18next';
import type { ChatAssessment } from '../hooks/useChat';

interface RecommendationCardProps {
  assessment: ChatAssessment;
}

export function RecommendationCard({ assessment }: RecommendationCardProps) {
  const { t } = useTranslation();

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
