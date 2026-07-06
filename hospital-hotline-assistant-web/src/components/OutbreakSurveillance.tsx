import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import type { SurveillanceSummaryOut } from '../api';

const PALETTE = [
  '#3b82f6', '#ef4444', '#f59e0b', '#10b981',
  '#8b5cf6', '#06b6d4', '#f97316', '#84cc16',
  '#ec4899', '#6366f1',
];

const SEVERITY_COLORS: Record<string, string> = {
  emergency: '#ef4444',
  urgent: '#f59e0b',
  general: '#10b981',
  unknown: '#94a3b8',
};

function BarChart({
  data,
  labelKey = 'keyword',
  valueKey = 'count',
  max,
}: {
  data: ReadonlyArray<object>;
  labelKey?: string;
  valueKey?: string;
  max?: number;
}) {
  const rows = data as ReadonlyArray<Record<string, unknown>>;
  const maxVal = max ?? Math.max(...rows.map((d) => Number(d[valueKey]) || 0), 1);
  return (
    <div className="surv-bar-chart">
      {rows.map((item, i) => {
        const pct = (Number(item[valueKey]) / maxVal) * 100;
        return (
          <div key={i} className="surv-bar-row">
            <span className="surv-bar-label" title={String(item[labelKey])}>
              {String(item[labelKey])}
            </span>
            <div className="surv-bar-track">
              <div
                className="surv-bar-fill"
                style={{ width: `${pct}%`, background: PALETTE[i % PALETTE.length] }}
              />
            </div>
            <span className="surv-bar-value">{String(item[valueKey])}</span>
          </div>
        );
      })}
    </div>
  );
}

function SparkLine({ data }: { data: Array<{ date: string; count: number }> }) {
  if (data.length === 0) return null;
  const max = Math.max(...data.map((d) => d.count), 1);
  const W = 480;
  const H = 80;
  const pad = 8;
  const step = (W - pad * 2) / Math.max(data.length - 1, 1);

  const points = data.map((d, i) => {
    const x = pad + i * step;
    const y = pad + (1 - d.count / max) * (H - pad * 2);
    return `${x},${y}`;
  });

  return (
    <div className="surv-sparkline-wrap">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="surv-sparkline"
        aria-hidden="true"
        preserveAspectRatio="none"
      >
        <polyline
          points={points.join(' ')}
          fill="none"
          stroke="#3b82f6"
          strokeWidth="2.5"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {data.map((d, i) => (
          <circle
            key={i}
            cx={pad + i * step}
            cy={pad + (1 - d.count / max) * (H - pad * 2)}
            r="3.5"
            fill="#3b82f6"
          />
        ))}
      </svg>
      <div className="surv-sparkline-labels">
        {data.map((d, i) => (
          <span key={i} className="surv-sparkline-label">
            {d.date.slice(5)}
          </span>
        ))}
      </div>
    </div>
  );
}

export function OutbreakSurveillance() {
  const { t } = useTranslation();
  const [days, setDays] = useState(7);
  const [data, setData] = useState<SurveillanceSummaryOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async (d: number) => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getSurveillanceSummary(d);
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('error'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load(days);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days]);

  const handleDaysChange = (d: number) => {
    setDays(d);
  };

  return (
    <div className="surv-container">
      <div className="surv-header">
        <div>
          <h2 className="surv-title">{t('surveillanceTitle')}</h2>
          <p className="surv-subtitle muted">{t('surveillanceSubtitle')}</p>
        </div>
        <div className="surv-day-filter">
          <span className="muted">{t('surveillanceDayFilter')}:</span>
          {([7, 14, 30] as const).map((d) => (
            <button
              key={d}
              type="button"
              className={`surv-day-btn ${days === d ? 'active' : ''}`}
              onClick={() => handleDaysChange(d)}
            >
              {t(`surveillanceDays${d}`)}
            </button>
          ))}
        </div>
      </div>

      {loading && (
        <div className="surv-loading">
          <span className="spinner" aria-hidden="true" />
          {t('loading')}
        </div>
      )}

      {error && (
        <div className="surv-error">
          <p>{error}</p>
          <button type="button" className="secondary-btn" onClick={() => void load(days)}>
            {t('retry')}
          </button>
        </div>
      )}

      {!loading && !error && data && (
        <>
          {/* Outbreak Alerts */}
          {data.outbreak_alerts.length > 0 && (
            <div className="surv-alerts">
              <h3 className="surv-section-title surv-alert-icon">
                ⚠ {t('surveillanceOutbreakAlerts')}
              </h3>
              <div className="surv-alert-grid">
                {data.outbreak_alerts.map((alert, i) => (
                  <div key={i} className="surv-alert-card">
                    <div className="surv-alert-keyword">{alert.keyword}</div>
                    {alert.area && (
                      <div className="surv-alert-area">
                        {t('surveillanceAlertArea')}: <strong>{alert.area}</strong>
                      </div>
                    )}
                    <div className="surv-alert-stats">
                      <span className="surv-alert-count">
                        {alert.recent_count} {t('surveillanceCases')}
                      </span>
                      <span className="surv-alert-increase">
                        ↑ {t('surveillanceAlertIncrease', { pct: alert.increase_pct })}
                      </span>
                    </div>
                    <div className="surv-alert-prev muted">
                      {t('surveillanceVsPrev')}: {alert.previous_count} {t('surveillanceCases')}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* KPI cards */}
          <div className="surv-kpi-row">
            <div className="surv-kpi-card">
              <span className="surv-kpi-value">{data.total_reports}</span>
              <span className="surv-kpi-label muted">{t('surveillanceTotalReports')}</span>
            </div>
            {data.severity_distribution.map((s) => (
              <div
                key={s.severity_level ?? 'unknown'}
                className="surv-kpi-card"
                style={{
                  borderTop: `3px solid ${SEVERITY_COLORS[s.severity_level ?? 'unknown'] ?? '#94a3b8'}`,
                }}
              >
                <span className="surv-kpi-value">{s.count}</span>
                <span className="surv-kpi-label muted">
                  {t(`severity_${s.severity_level ?? 'unknown'}` as never, {
                    defaultValue: s.severity_level ?? 'Unknown',
                  })}
                </span>
              </div>
            ))}
          </div>

          {data.total_reports === 0 ? (
            <div className="surv-empty">{t('surveillanceNoData')}</div>
          ) : (
            <div className="surv-grid">
              {/* Top symptoms */}
              <div className="surv-panel">
                <h3 className="surv-section-title">{t('surveillanceTopSymptoms')}</h3>
                {data.top_symptoms.length === 0 ? (
                  <p className="muted">{t('surveillanceNoData')}</p>
                ) : (
                  <BarChart data={data.top_symptoms} />
                )}
              </div>

              {/* Daily trend */}
              <div className="surv-panel">
                <h3 className="surv-section-title">{t('surveillanceDailyTrend')}</h3>
                {data.daily_trend.length === 0 ? (
                  <p className="muted">{t('surveillanceNoData')}</p>
                ) : (
                  <SparkLine data={data.daily_trend} />
                )}
              </div>

              {/* By area */}
              {data.by_area.length > 0 && (
                <div className="surv-panel surv-panel-full">
                  <h3 className="surv-section-title">{t('surveillanceByArea')}</h3>
                  <div className="surv-area-table-wrap">
                    <table className="surv-area-table">
                      <thead>
                        <tr>
                          <th>{t('surveillanceAlertArea')}</th>
                          <th>Symptom</th>
                          <th>{t('surveillanceCases')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.by_area.map((row, i) => (
                          <tr key={i}>
                            <td>{row.area}</td>
                            <td>{row.keyword}</td>
                            <td>
                              <span className="surv-count-badge">{row.count}</span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {!loading && !error && !data && (
        <div className="surv-empty">{t('surveillanceNoData')}</div>
      )}
    </div>
  );
}
