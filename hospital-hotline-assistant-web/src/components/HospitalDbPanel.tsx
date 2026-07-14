import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import type { HisVisitDetail, HisVisitSummary } from '../api/types';

function ageFromBirthdate(birthdate: string | null): string {
  if (!birthdate) return '—';
  const born = new Date(birthdate);
  if (Number.isNaN(born.getTime())) return '—';
  const now = new Date();
  let age = now.getFullYear() - born.getFullYear();
  const m = now.getMonth() - born.getMonth();
  if (m < 0 || (m === 0 && now.getDate() < born.getDate())) age -= 1;
  return String(age);
}

/** A single field row that reads blank vs filled, tagged by write stage. */
function Field({ label, value, stage }: { label: string; value: unknown; stage?: string }) {
  const filled = value !== null && value !== undefined && value !== '';
  return (
    <div className={`hdb-field ${filled ? 'filled' : 'blank'}`}>
      <span className="hdb-field-label">
        {label}
        {stage ? <span className={`hdb-stage-tag hdb-stage-${stage}`}>{stage}</span> : null}
      </span>
      <span className="hdb-field-value">{filled ? String(value) : '—'}</span>
    </div>
  );
}

export function HospitalDbPanel() {
  const { t } = useTranslation();
  const [available, setAvailable] = useState(true);
  const [visits, setVisits] = useState<HisVisitSummary[]>([]);
  const [selected, setSelected] = useState<HisVisitDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadVisits = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getHisVisits();
      setAvailable(res.available);
      setVisits(res.visits);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadVisits();
  }, [loadVisits]);

  const openVisit = async (visitId: string) => {
    try {
      const res = await api.getHisVisit(visitId);
      setSelected(res.visit);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const refresh = async () => {
    await loadVisits();
    if (selected) await openVisit(selected.visit_id);
  };

  return (
    <div className="hdb-panel">
      <div className="hdb-header">
        <div>
          <h2>{t('hdbTitle')}</h2>
          <p className="muted">{t('hdbSubtitle')}</p>
        </div>
        <button type="button" className="secondary-btn" onClick={() => void refresh()}>
          {t('hdbRefresh')}
        </button>
      </div>

      {error && <p className="error-text">{error}</p>}

      {!available ? (
        <p className="muted hdb-unavailable">{t('hdbUnavailable')}</p>
      ) : loading ? (
        <p className="muted">{t('loading')}</p>
      ) : (
        <div className="hdb-body">
          <div className="hdb-list">
            <table className="hdb-table">
              <thead>
                <tr>
                  <th>{t('hdbVisitId')}</th>
                  <th>{t('hdbHn')}</th>
                  <th>{t('hdbPatientName')}</th>
                  <th>{t('hdbAge')}</th>
                  <th>{t('hdbStatus')}</th>
                </tr>
              </thead>
              <tbody>
                {visits.map((v) => (
                  <tr
                    key={v.visit_id}
                    className={selected?.visit_id === v.visit_id ? 'active' : ''}
                    onClick={() => void openVisit(v.visit_id)}
                  >
                    <td><code>{v.visit_id.slice(-8)}</code></td>
                    <td>{v.hnx ?? '—'}</td>
                    <td>{v.patient_name?.trim() || '—'}</td>
                    <td>{ageFromBirthdate(v.birthdate)}</td>
                    <td>
                      <span className={`hdb-status hdb-status-${v.screening_status}`}>
                        {t(`hdbState_${v.screening_status}`)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {selected && (
            <div className="hdb-detail">
              <div className="hdb-detail-head">
                <code>{selected.visit_id}</code>
                <span className={`hdb-status hdb-status-${selected.screening_status}`}>
                  {t(`hdbState_${selected.screening_status}`)}
                </span>
              </div>

              <h4>{t('hdbGroupRegistered')}</h4>
              <Field label={t('hdbHn')} value={selected.hnx} />
              <Field label={t('hdbPatientName')} value={selected.patient_name} />
              <Field label={t('hdbBirthdate')} value={selected.birthdate} />
              <Field label={t('hdbAppointment')} value={selected.appointment ? t('hdbYes') : t('hdbNo')} />

              <h4>{t('hdbGroupStage1')}</h4>
              <Field label={t('hdbPressure')} value={selected.vitals.pressure} stage="1" />
              <Field label={t('hdbPulse')} value={selected.vitals.pulse} stage="1" />
              <Field label={t('hdbWeight')} value={selected.vitals.weight} stage="1" />
              <Field label={t('hdbHeight')} value={selected.vitals.height} stage="1" />
              <Field label={t('hdbBmi')} value={selected.vitals.bmi} stage="1" />
              <Field label={t('hdbTemperature')} value={selected.vitals.temperature} stage="1" />
              <Field label={t('hdbWaist')} value={selected.vitals.waist_width} />
              <Field label={t('hdbFirstLocation')} value={selected.first_location.department} stage="1" />
              <Field label={t('hdbFollowUp')} value={selected.follow_up} stage="1" />

              <h4>{t('hdbGroupStage2')}</h4>
              <Field label={t('hdbChiefComplaint')} value={selected.nurse_chief_complaint} stage="2" />
              <Field label={t('hdbIllness')} value={selected.nurse_patient_illness} stage="2" />
              <Field label={t('hdbSecondLocation')} value={selected.second_location.department} stage="2" />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
