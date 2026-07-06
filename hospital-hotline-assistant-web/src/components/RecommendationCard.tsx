import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import type { ChatAssessment } from '../hooks/useChat';

interface RecommendationCardProps {
  assessment: ChatAssessment;
  autoOpenMap?: boolean;
}

function localizeClinicalDetail(text: string | undefined, language: string): string | undefined {
  const trimmed = text?.trim();
  if (!trimmed) {
    return undefined;
  }

  if (!language.startsWith('th')) {
    return trimmed;
  }

  return trimmed
    .replace(/No signs of respiratory distress or severe pain\.?/gi, 'ไม่มีสัญญาณหายใจลำบากหรือปวดรุนแรง')
    .replace(/respiratory distress/gi, 'หายใจลำบาก')
    .replace(/severe pain/gi, 'ปวดรุนแรง')
    .replace(/sore throat/gi, 'เจ็บคอ')
    .replace(/headache/gi, 'ปวดหัว')
    .replace(/fever/gi, 'มีไข้')
    .replace(/,\s*/g, ' ')
    .replace(/\.\s*/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export function RecommendationCard({ assessment, autoOpenMap = false }: RecommendationCardProps) {
  const { t, i18n } = useTranslation();
  const [showMapPopup, setShowMapPopup] = useState(autoOpenMap);

  useEffect(() => {
    if (autoOpenMap) {
      setShowMapPopup(true);
    }
  }, [autoOpenMap]);
  const redFlags = assessment.symptoms?.redFlags ?? [];

  if (!assessment.severity && !assessment.department) {
    return null;
  }

  // Map AI department codes to our route finder keys
  const getMapDestinationKey = (codeOrId: string) => {
    const normalized = codeOrId.toLowerCase().replace('dept_', '').replace('opd_', '');
    const validKeys = [
      'entrance', 'publicWaiting', 'mainHallway', 'counter', 'emergency',
      'opd', 'neurology', 'cardiology', 'pediatrics', 'orthopedics',
      'gynecology', 'gastroenterology', 'ent', 'teeth'
    ];
    if (validKeys.includes(normalized)) return normalized;
    if (normalized.includes('dental')) return 'teeth';
    if (normalized.includes('reception')) return 'counter';
    if (normalized.includes('neuro')) return 'neurology';
    if (normalized.includes('cardio')) return 'cardiology';
    // Fallback: general OPD
    if (normalized === 'general') return 'opd';
    return null;
  };

  const mapDestination = assessment.department 
    ? getMapDestinationKey(assessment.department.code ?? assessment.department.departmentId) 
    : null;
  const severityDetail = localizeClinicalDetail(
    assessment.severity?.explanation,
    i18n.language,
  );

  return (
    <>
      <div className="recommendation-card">
        <h3>{t('recommendationTitle')}</h3>
        {assessment.severity && (
          <p>
            <strong>{t('severity')}:</strong>{' '}
            <span className={`severity-badge severity-${assessment.severity.level}`}>
              {t(`severity_${assessment.severity.level}`)}
            </span>
            {severityDetail && (
              <span className="recommendation-detail"> — {severityDetail}</span>
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
          </p>
        )}
        
        {mapDestination && (
          <div 
            style={{ marginTop: '16px', borderRadius: '8px', overflow: 'hidden', border: '1px solid var(--border)', aspectRatio: '637/454', cursor: 'pointer', position: 'relative' }}
            onClick={() => setShowMapPopup(true)}
          >
            <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, zIndex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(0,0,0,0.1)' }}>
               <div style={{ backgroundColor: 'var(--bg)', padding: '8px 16px', borderRadius: '20px', fontWeight: 600, boxShadow: '0 2px 8px rgba(0,0,0,0.1)' }}>
                  {t('tapToViewMap', 'Tap to view interactive map')}
               </div>
            </div>
            <iframe 
              src={`/hospital-map/index.html?destination=${mapDestination}&embedded=true`} 
              style={{ width: '100%', height: '100%', border: 'none', display: 'block', pointerEvents: 'none' }}
              title="Hospital Route Map Preview"
            />
          </div>
        )}
      </div>

      {showMapPopup && mapDestination && (
        <div className="patient-id-modal" role="dialog" aria-modal="true">
          <button
            type="button"
            className="patient-id-modal-backdrop"
            aria-label={t('close')}
            onClick={() => setShowMapPopup(false)}
          />
          <div className="patient-id-modal-card" style={{ maxWidth: '800px', padding: 0, overflow: 'hidden' }}>
            <div style={{ padding: '16px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', backgroundColor: 'var(--bg)' }}>
              <h3 style={{ margin: 0 }}>{t('hospitalMap', 'Hospital Route Map')}</h3>
              <button 
                onClick={() => setShowMapPopup(false)}
                style={{
                  background: 'none', border: 'none', fontSize: '24px', cursor: 'pointer', color: 'var(--text)', padding: '0 8px'
                }}
              >
                &times;
              </button>
            </div>
            <iframe 
              src={`/hospital-map/index.html?destination=${mapDestination}&embedded=true`} 
              style={{ width: '100%', border: 'none', display: 'block', aspectRatio: '637/454' }}
              title="Hospital Route Map Interactive"
            />
            <div style={{ padding: '16px', borderTop: '1px solid var(--border)', backgroundColor: 'var(--bg)', display: 'flex', justifyContent: 'center' }}>
              <button 
                className="secondary-btn"
                style={{ width: '100%' }}
                onClick={() => setShowMapPopup(false)}
              >
                {t('closeMap', 'Close Map')}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
