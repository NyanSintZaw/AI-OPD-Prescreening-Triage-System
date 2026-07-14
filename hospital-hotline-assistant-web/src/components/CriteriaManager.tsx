import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  api,
  type AiMetricsOut,
  type CriteriaDiffOut,
  type CriteriaVersionDetail,
  type CriteriaVersionSummary,
} from '../api';
import type { CriteriaVersionStatus } from '../api/types';

const POLL_INTERVAL_MS = 3000; // poll while background rule extraction runs
const MAX_FILE_MB = 50;
const ACCEPTED_EXTENSIONS = ['.pdf', '.txt', '.md', '.csv', '.docx'];

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString();
}

export function CriteriaManager() {
  const { t } = useTranslation();

  const [versions, setVersions] = useState<CriteriaVersionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);

  const [selected, setSelected] = useState<CriteriaVersionDetail | null>(null);
  const [diff, setDiff] = useState<CriteriaDiffOut | null>(null);
  const [editText, setEditText] = useState<string | null>(null);
  const [editErrors, setEditErrors] = useState<string[]>([]);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadVersions = useCallback(async () => {
    try {
      const data = await api.listCriteriaVersions();
      setVersions(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('error'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadVersions();
  }, [loadVersions]);

  // Poll while any version is still extracting
  const anyProcessing = versions.some((v) => v.processing);
  useEffect(() => {
    if (anyProcessing) {
      pollRef.current = setInterval(() => void loadVersions(), POLL_INTERVAL_MS);
    } else if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [anyProcessing, loadVersions]);

  // ── upload ──────────────────────────────────────────────────────────────────
  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (fileInputRef.current) fileInputRef.current.value = '';
    if (!file) return;
    const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
    if (!ACCEPTED_EXTENSIONS.includes(ext)) {
      setError(t('criteriaUploadHint'));
      return;
    }
    if (file.size > MAX_FILE_MB * 1024 * 1024) {
      setError(`File too large (max ${MAX_FILE_MB} MB).`);
      return;
    }
    setUploading(true);
    setError(null);
    try {
      await api.uploadScreeningCriteria(file);
      await loadVersions();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('error'));
    } finally {
      setUploading(false);
    }
  };

  // ── selection / detail ──────────────────────────────────────────────────────
  const selectVersion = async (versionId: string) => {
    if (selected?.id === versionId) {
      setSelected(null);
      setDiff(null);
      setEditText(null);
      return;
    }
    setBusy(true);
    setDiff(null);
    setEditText(null);
    setEditErrors([]);
    try {
      setSelected(await api.getCriteriaVersion(versionId));
    } catch (err) {
      setError(err instanceof Error ? err.message : t('error'));
    } finally {
      setBusy(false);
    }
  };

  const refreshSelected = async (versionId: string) => {
    await loadVersions();
    try {
      setSelected(await api.getCriteriaVersion(versionId));
    } catch {
      setSelected(null);
    }
  };

  const runAction = async (action: () => Promise<unknown>, versionId: string) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      await refreshSelected(versionId);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('error'));
    } finally {
      setBusy(false);
    }
  };

  const handleDiff = async (versionId: string) => {
    setBusy(true);
    setError(null);
    try {
      setDiff(await api.getCriteriaDiff(versionId));
    } catch (err) {
      setError(err instanceof Error ? err.message : t('error'));
    } finally {
      setBusy(false);
    }
  };

  const handleSaveEdit = async () => {
    if (!selected || editText == null) return;
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(editText) as Record<string, unknown>;
    } catch {
      setEditErrors([t('criteriaInvalidJson')]);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api.updateCriteriaVersion(selected.id, parsed);
      setEditErrors(result.validation_errors);
      if (result.validation_errors.length === 0) {
        setEditText(null);
      }
      await refreshSelected(selected.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('error'));
    } finally {
      setBusy(false);
    }
  };

  const handleActivate = (versionId: string) => {
    if (!window.confirm(t('criteriaConfirmActivate'))) return;
    void runAction(() => api.activateCriteriaVersion(versionId), versionId);
  };

  const statusLabel = (status: CriteriaVersionStatus) => t(`criteriaStatus_${status}`);

  const editable = selected && (selected.status === 'draft' || selected.status === 'pending_review');

  // ── render ──────────────────────────────────────────────────────────────────
  return (
    <section className="tm-section">
      <header className="tm-header">
        <h2>{t('criteriaTitle')}</h2>
        <p className="muted">{t('criteriaSubtitle')}</p>
      </header>

      {error && (
        <p className="tm-upload-error" role="alert">
          ⚠ {error}
        </p>
      )}

      <div className="tm-actions cm-upload-row">
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_EXTENSIONS.join(',')}
          className="tm-file-input"
          onChange={(e) => void handleFileChange(e)}
          aria-hidden="true"
          tabIndex={-1}
        />
        <button
          type="button"
          className="primary-btn"
          disabled={uploading}
          onClick={() => fileInputRef.current?.click()}
        >
          {uploading ? <span className="tm-spinner" aria-hidden="true" /> : null}
          {t('criteriaUploadBtn')}
        </button>
        <span className="muted cm-upload-hint">{t('criteriaUploadHint')}</span>
      </div>

      {loading ? (
        <p className="muted">{t('loading')}</p>
      ) : versions.length === 0 ? (
        <p className="muted">{t('criteriaNoVersions')}</p>
      ) : (
        <div className="table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>{t('criteriaVersion')}</th>
                <th>{t('status')}</th>
                <th>{t('criteriaChangeSummary')}</th>
                <th>{t('criteriaUploadedBy')}</th>
                <th>{t('started')}</th>
                <th aria-label="actions" />
              </tr>
            </thead>
            <tbody>
              {versions.map((row) => (
                <tr
                  key={row.id}
                  className={`admin-row ${selected?.id === row.id ? 'selected' : ''}`}
                >
                  <td>v{row.version_no}</td>
                  <td>
                    <span className={`cm-status-pill cm-status-${row.status}`}>
                      {statusLabel(row.status)}
                    </span>
                    {row.processing && (
                      <span className="tm-spinner" aria-label={t('criteriaProcessing')} />
                    )}
                  </td>
                  <td className="cm-summary-cell">{row.change_summary || '—'}</td>
                  <td>{row.uploaded_by ?? '—'}</td>
                  <td>{formatDate(row.created_at)}</td>
                  <td className="admin-col-actions">
                    <button
                      type="button"
                      className="secondary-btn admin-row-btn"
                      onClick={() => void selectVersion(row.id)}
                    >
                      {selected?.id === row.id ? t('close') : t('criteriaView')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <div className="cm-detail">
          <div className="cm-detail-header">
            <h3>
              v{selected.version_no} —{' '}
              <span className={`cm-status-pill cm-status-${selected.status}`}>
                {statusLabel(selected.status)}
              </span>
            </h3>
            <div className="cm-detail-actions">
              {selected.status === 'draft' && !selected.processing && (
                <button
                  type="button"
                  className="primary-btn"
                  disabled={busy}
                  onClick={() =>
                    void runAction(() => api.submitCriteriaVersion(selected.id), selected.id)
                  }
                >
                  {t('criteriaSubmit')}
                </button>
              )}
              {selected.status === 'pending_review' && (
                <button
                  type="button"
                  className="primary-btn"
                  disabled={busy}
                  onClick={() =>
                    void runAction(() => api.approveCriteriaVersion(selected.id), selected.id)
                  }
                >
                  {t('criteriaApprove')}
                </button>
              )}
              {selected.status === 'approved' && (
                <button
                  type="button"
                  className="primary-btn"
                  disabled={busy}
                  onClick={() => handleActivate(selected.id)}
                >
                  {t('criteriaActivate')}
                </button>
              )}
              {selected.status === 'retired' && (
                <button
                  type="button"
                  className="secondary-btn"
                  disabled={busy}
                  onClick={() => handleActivate(selected.id)}
                >
                  {t('criteriaRollback')}
                </button>
              )}
              {selected.status !== 'active' && (
                <button
                  type="button"
                  className="secondary-btn"
                  disabled={busy}
                  onClick={() => void handleDiff(selected.id)}
                >
                  {t('criteriaDiffBtn')}
                </button>
              )}
              {editable && editText == null && (
                <button
                  type="button"
                  className="secondary-btn"
                  disabled={busy}
                  onClick={() => setEditText(JSON.stringify(selected.criteria, null, 2))}
                >
                  {t('criteriaEditBtn')}
                </button>
              )}
            </div>
          </div>

          {selected.validation_errors.length > 0 ? (
            <div className="cm-validation-errors" role="alert">
              <strong>{t('criteriaValidationErrors')}</strong>
              <ul>
                {selected.validation_errors.slice(0, 10).map((msg) => (
                  <li key={msg}>{msg}</li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="cm-valid muted">✓ {t('criteriaValid')}</p>
          )}

          {diff && (
            <div className="cm-diff">
              <h4>
                {t('criteriaDiffBtn')} ({diff.against})
              </h4>
              {Object.keys(diff.diff).length === 0 ? (
                <p className="muted">{t('criteriaDiffEmpty')}</p>
              ) : (
                <table className="admin-table cm-diff-table">
                  <thead>
                    <tr>
                      <th>{t('criteriaDiffSection')}</th>
                      <th>{t('criteriaDiffAdded')}</th>
                      <th>{t('criteriaDiffRemoved')}</th>
                      <th>{t('criteriaDiffChanged')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(diff.diff).map(([section, changes]) => (
                      <tr key={section}>
                        <td>
                          <code>{section}</code>
                        </td>
                        <td className="cm-diff-added">{changes.added.join(', ') || '—'}</td>
                        <td className="cm-diff-removed">{changes.removed.join(', ') || '—'}</td>
                        <td className="cm-diff-changed">{changes.changed.join(', ') || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {editText != null && (
            <div className="cm-editor">
              {editErrors.length > 0 && (
                <div className="cm-validation-errors" role="alert">
                  <ul>
                    {editErrors.slice(0, 10).map((msg) => (
                      <li key={msg}>{msg}</li>
                    ))}
                  </ul>
                </div>
              )}
              <textarea
                className="cm-editor-textarea"
                value={editText}
                onChange={(e) => setEditText(e.target.value)}
                spellCheck={false}
                rows={20}
              />
              <div className="cm-detail-actions">
                <button
                  type="button"
                  className="primary-btn"
                  disabled={busy}
                  onClick={() => void handleSaveEdit()}
                >
                  {t('criteriaSave')}
                </button>
                <button
                  type="button"
                  className="secondary-btn"
                  disabled={busy}
                  onClick={() => {
                    setEditText(null);
                    setEditErrors([]);
                  }}
                >
                  {t('close')}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      <AiMetricsPanel />
    </section>
  );
}

// ── AI transparency metrics (SRS F40) ────────────────────────────────────────

export function AiMetricsPanel() {
  const { t } = useTranslation();
  const [metrics, setMetrics] = useState<AiMetricsOut | null>(null);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (from?: string, to?: string) => {
    setLoading(true);
    setError(null);
    try {
      setMetrics(await api.getAiMetrics({ from: from || undefined, to: to || undefined }));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const hasData =
    metrics != null &&
    (metrics.call_sites.length > 0 ||
      metrics.dispositions.length > 0 ||
      (metrics.totals.dispositions ?? 0) > 0);

  return (
    <div className="cm-metrics">
      <header className="tm-header">
        <h3>{t('aiMetricsTitle')}</h3>
        <p className="muted">{t('aiMetricsSubtitle')}</p>
      </header>

      <div className="cm-metrics-filter">
        <label>
          {t('aiMetricsFrom')}
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </label>
        <label>
          {t('aiMetricsTo')}
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </label>
        <button
          type="button"
          className="secondary-btn"
          disabled={loading}
          onClick={() => void load(dateFrom, dateTo)}
        >
          {t('aiMetricsApply')}
        </button>
      </div>

      {error && (
        <p className="tm-upload-error" role="alert">
          ⚠ {error}
        </p>
      )}

      {loading ? (
        <p className="muted">{t('loading')}</p>
      ) : !hasData ? (
        <p className="muted">{t('aiMetricsNoData')}</p>
      ) : (
        metrics && (
          <>
            <div className="kpi-grid cm-metrics-kpis">
              <div className="kpi-card tone-neutral">
                <span className="kpi-label">{t('aiMetricsSessions')}</span>
                <span className="kpi-value">{metrics.totals.sessions ?? 0}</span>
              </div>
              <div className="kpi-card tone-neutral">
                <span className="kpi-label">{t('aiMetricsDispositions')}</span>
                <span className="kpi-value">{metrics.totals.dispositions ?? 0}</span>
              </div>
              <div className="kpi-card tone-urgent">
                <span className="kpi-label">{t('aiMetricsEscalations')}</span>
                <span className="kpi-value">{metrics.totals.escalations ?? 0}</span>
              </div>
              <div className="kpi-card tone-alert">
                <span className="kpi-label">{t('aiMetricsExtractionFailures')}</span>
                <span className="kpi-value">{metrics.totals.extraction_failures ?? 0}</span>
              </div>
            </div>

            <div className="cm-metrics-tables">
              <div className="table-wrap">
                <h4>{t('aiMetricsCallSites')}</h4>
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>{t('aiMetricsCallSite')}</th>
                      <th className="admin-col-num">{t('aiMetricsCalls')}</th>
                      <th className="admin-col-num">{t('aiMetricsOkRate')}</th>
                      <th className="admin-col-num">{t('aiMetricsLatency')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.call_sites.map((row) => (
                      <tr key={row.call_site}>
                        <td>
                          <code>{row.call_site}</code>
                        </td>
                        <td className="admin-col-num">{row.calls}</td>
                        <td className="admin-col-num">
                          {row.ok_rate != null ? `${(row.ok_rate * 100).toFixed(1)}%` : '—'}
                        </td>
                        <td className="admin-col-num">{row.avg_latency_ms ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="table-wrap">
                <h4>{t('aiMetricsByLevel')}</h4>
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>{t('aiMetricsLevel')}</th>
                      <th>{t('department')}</th>
                      <th className="admin-col-num">{t('aiMetricsCount')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.dispositions.map((row) => (
                      <tr key={`${row.level}-${row.department_code}`}>
                        <td>{row.level ?? '—'}</td>
                        <td>
                          <code>{row.department_code ?? '—'}</code>
                        </td>
                        <td className="admin-col-num">{row.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {metrics.validator_violations.length > 0 && (
                <div className="table-wrap">
                  <h4>{t('aiMetricsViolations')}</h4>
                  <table className="admin-table">
                    <thead>
                      <tr>
                        <th>{t('aiMetricsViolation')}</th>
                        <th className="admin-col-num">{t('aiMetricsCount')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {metrics.validator_violations.map((row) => (
                        <tr key={row.violation}>
                          <td>
                            <code>{row.violation}</code>
                          </td>
                          <td className="admin-col-num">{row.count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )
      )}
    </div>
  );
}
