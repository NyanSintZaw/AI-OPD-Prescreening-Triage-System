import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import type { ChatAssessment } from '../hooks/useChat';

interface RecommendationCardProps {
  assessment: ChatAssessment;
  autoOpenMap?: boolean;
}

export function RecommendationCard({ assessment, autoOpenMap = false }: RecommendationCardProps) {
  const { t, i18n } = useTranslation();
  const [showMapPopup, setShowMapPopup] = useState(autoOpenMap);

  useEffect(() => {
    if (autoOpenMap) {
      setShowMapPopup(true);
    }
  }, [autoOpenMap]);

  // The viewer's Back button posts carenav:back from inside the iframe.
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      if ((event.data as { type?: string } | null)?.type === 'carenav:back') {
        setShowMapPopup(false);
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  if (!assessment.severity && !assessment.department) {
    return null;
  }

  // Map AI department codes to locations on the CareNav wayfinder map.
  // The viewer resolves these case-insensitively against its location ids
  // and labels; departments without their own room on the map route to
  // general OPD, matching the OPD-first policy.
  const getMapDestinationKey = (codeOrId: string) => {
    const normalized = codeOrId.toLowerCase().replace('dept_', '').replace('opd_', '');
    if (normalized.includes('emergency') || normalized === 'er') return 'emergency';
    if (normalized.includes('cardio')) return 'cardiology';
    if (normalized.includes('neuro')) return 'neurology';
    if (normalized.includes('pediatric') || normalized.includes('paediatric')) return 'pediatrics';
    return 'opd';
  };

  const mapDestination = assessment.department
    ? getMapDestinationKey(assessment.department.code ?? assessment.department.departmentId)
    : null;

  // Patients only ever see WHERE to go — never the triage level, scores, or
  // red flags. Clinical detail stays on the nurse/admin surfaces.
  return (
    <>
      <div className="recommendation-card">
        <h3>{t('recommendationTitle')}</h3>
        {assessment.department && (
          <p>
            <strong>{t('department')}:</strong>{' '}
            {assessment.department.name ?? assessment.department.departmentId}
          </p>
        )}
        {assessment.department && (
          <p className="recommendation-detail">
            {assessment.department.navLine ||
              t('proceedToGuidance', {
                department:
                  assessment.department.name ?? assessment.department.departmentId,
              })}
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
        <div className="patient-id-modal map-modal" role="dialog" aria-modal="true">
          <button
            type="button"
            className="patient-id-modal-backdrop"
            aria-label={t('close')}
            onClick={() => setShowMapPopup(false)}
          />
          <div className="patient-id-modal-card map-modal-card">
            <iframe
              src={`/hospital-map/index.html?destination=${mapDestination}&lang=${i18n.language}`}
              className="map-modal-frame"
              title={t('hospitalMap', 'Hospital Route Map')}
            />
          </div>
        </div>
      )}
    </>
  );
}
