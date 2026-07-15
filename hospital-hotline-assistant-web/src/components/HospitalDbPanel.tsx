import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import { getAdminRole } from '../api/client';
import type { HisConnection, HisVisitDetail, HisVisitSummary } from '../api/types';

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

/** Connection setup / status for the hospital DB — the demo's "the hospital
 *  plugs its database into our system" moment. Two fields for now: endpoint
 *  and a display name that becomes the panel title. */
function ConnectionCard({
  conn,
  onConnected,
}: {
  conn: HisConnection | null;
  onConnected: (next: HisConnection) => void;
}) {
  const { t } = useTranslation();
  const canEdit = getAdminRole() === 'super_admin';
  const connected = Boolean(conn?.connected);
  const [open, setOpen] = useState(!connected);
  const [endpoint, setEndpoint] = useState(conn?.endpoint ?? 'http://localhost:8001');
  const [name, setName] = useState(conn?.name ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);

  // Keep the collapsed/expanded state in sync when the connection loads.
  useEffect(() => {
    setOpen(!connected);
    if (conn?.endpoint) setEndpoint(conn.endpoint);
    if (conn?.name) setName(conn.name);
  }, [connected, conn?.endpoint, conn?.name]);

  const connect = async () => {
    if (!endpoint.trim() || !name.trim()) {
      setError(t('hdbConnRequired'));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const next = await api.updateHisConnection({
        endpoint: endpoint.trim(),
        name: name.trim(),
      });
      onConnected(next);
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const disconnect = async () => {
    setBusy(true);
    setError(null);
    try {
      const next = await api.disconnectHisConnection();
      setConfirmDisconnect(false);
      onConnected(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`hdb-connection ${connected ? 'connected' : 'disconnected'}`}>
      <div className="hdb-connection-status">
        <span className={`hdb-conn-dot ${connected ? 'ok' : 'off'}`} aria-hidden="true" />
        <span className="hdb-conn-text">
          {connected
            ? t('hdbConnConnected', {
                endpoint: conn?.endpoint ?? '',
                count: conn?.visit_count ?? 0,
              })
            : t('hdbConnNotConnected')}
        </span>
        {connected && canEdit && (
          <>
            <button type="button" className="text-btn" onClick={() => setOpen((v) => !v)}>
              {t('hdbConnChange')}
            </button>
            <button
              type="button"
              className="text-btn users-danger"
              onClick={() => setConfirmDisconnect(true)}
              disabled={busy}
            >
              {t('hdbConnDisconnect')}
            </button>
          </>
        )}
      </div>

      {confirmDisconnect && (
        <div className="hdb-modal-backdrop" role="presentation">
          <div className="hdb-modal" role="alertdialog" aria-modal="true">
            <h3>{t('hdbConnDisconnectTitle')}</h3>
            <p className="muted">{t('hdbConnDisconnectBody', { name: conn?.name ?? '' })}</p>
            {error && <p className="error-text">{error}</p>}
            <div className="hdb-modal-actions">
              <button
                type="button"
                className="secondary-btn users-danger"
                onClick={() => void disconnect()}
                disabled={busy}
              >
                {busy ? t('loading') : t('hdbConnDisconnectConfirm')}
              </button>
              <button
                type="button"
                className="text-btn"
                onClick={() => setConfirmDisconnect(false)}
                disabled={busy}
              >
                {t('usersCancel')}
              </button>
            </div>
          </div>
        </div>
      )}
      {conn?.message && !connected && <p className="error-text">{conn.message}</p>}

      {open && canEdit && (
        <div className="hdb-connection-form">
          <label className="vitals-extra-field">
            <span>{t('hdbConnEndpoint')}</span>
            <input
              type="url"
              placeholder="http://localhost:8001"
              value={endpoint}
              onChange={(e) => setEndpoint(e.target.value)}
              disabled={busy}
            />
          </label>
          <label className="vitals-extra-field">
            <span>{t('hdbConnName')}</span>
            <input
              type="text"
              placeholder={t('hdbConnNamePlaceholder')}
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={busy}
              maxLength={120}
            />
          </label>
          <button
            type="button"
            className="primary-btn"
            onClick={() => void connect()}
            disabled={busy || !endpoint.trim() || !name.trim()}
          >
            {busy ? t('hdbConnConnecting') : t('hdbConnConnect')}
          </button>
          {error && <p className="error-text">{error}</p>}
        </div>
      )}
      {open && !canEdit && !connected && (
        <p className="muted">{t('hdbConnAskAdmin')}</p>
      )}
    </div>
  );
}

export function HospitalDbPanel() {
  const { t } = useTranslation();
  const [conn, setConn] = useState<HisConnection | null>(null);
  const [available, setAvailable] = useState(true);
  const [visits, setVisits] = useState<HisVisitSummary[]>([]);
  const [selected, setSelected] = useState<HisVisitDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadVisits = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const connection = await api.getHisConnection();
      setConn(connection);
      if (!connection.connected) {
        setAvailable(false);
        setVisits([]);
        return;
      }
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
          <h2>{conn?.connected && conn.name ? conn.name : t('hdbTitle')}</h2>
          <p className="muted">{t('hdbSubtitle')}</p>
        </div>
        <button type="button" className="secondary-btn" onClick={() => void refresh()}>
          {t('hdbRefresh')}
        </button>
      </div>

      <ConnectionCard
        conn={conn}
        onConnected={() => void loadVisits()}
      />

      {error && <p className="error-text">{error}</p>}

      {!available ? (
        !loading && !conn?.connected ? null : (
          <p className="muted hdb-unavailable">{t('hdbUnavailable')}</p>
        )
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
