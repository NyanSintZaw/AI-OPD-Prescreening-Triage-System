/**
 * The one dashboard, mounted in both staff portals.
 *
 * `scope="nurse"` answers "how busy is my floor right now and how sick are
 * they"; `scope="admin"` adds the volume trend behind it. Everything comes
 * from two calls — `/admin/triage-stats` (dense series, computed in SQL) and
 * `/admin/surveillance` (symptom counts) — so no panel derives a number from
 * a capped 100-row page the way the old admin KPI row did.
 *
 * Colour rules this file obeys, because a validator run said so:
 *  - The MOPH triage colours are clinical and cannot be re-picked, but
 *    level 1 vs level 2 sit at ΔE 13.1 for NORMAL vision — under the 15 floor.
 *    So acuity is never encoded by colour alone: every mark carries its
 *    number and its label. Colour is the supporting stripe, not the signal.
 *  - Every other chart is single-hue magnitude. The old rainbow gave eight
 *    hues to eight bars that were all length 1, which encoded nothing.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowUp, Minus, WarningCircle } from '@phosphor-icons/react';
import { api } from '../api';
import type { RoutingFeedbackOut, SurveillanceSummaryOut, TriageStatsOut } from '../api/types';
import { useLanguage } from '../hooks/useSession';
import { useDuration } from '../hooks/useDuration';

type Scope = 'nurse' | 'admin';

const DAY_OPTIONS = [7, 14, 30] as const;

/** MOPH level → the token that carries it. Levels are ordinal, not categorical. */
const LEVEL_TOKEN: Record<number, string> = {
  1: 'var(--triage-1)',
  2: 'var(--triage-2)',
  3: 'var(--triage-3)',
  4: 'var(--triage-4)',
  5: 'var(--triage-5)',
};

const nf = new Intl.NumberFormat();

/**
 * Is this keyword a symptom term, or a whole utterance?
 *
 * Two writers feed `symptom_keywords`: the extractor writes short terms, and
 * the turn pipeline writes the free-text `symptoms_summary`. The second kind
 * arrived as a sibling "symptom" — a full Thai sentence ranked next to
 * "fever". Thai does not put spaces between words, so a word count cannot
 * tell the two apart; character length can.
 */
function isSymptomTerm({ keyword }: { keyword: string }): boolean {
  const term = keyword.trim();
  return term.length > 0 && term.length <= 24 && term.split(/\s+/).length <= 3;
}

function StatTile({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string | null;
  tone?: 'default' | 'attention' | 'good';
}) {
  return (
    <div className={`stat-tile ${tone && tone !== 'default' ? `stat-tile-${tone}` : ''}`}>
      <p className="stat-tile-label">{label}</p>
      <p className="stat-tile-value">{value}</p>
      {hint ? <p className="stat-tile-hint">{hint}</p> : null}
    </div>
  );
}

function Panel({
  title,
  subtitle,
  children,
  wide,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  wide?: boolean;
}) {
  return (
    <section className={`dash-panel ${wide ? 'dash-panel-wide' : ''}`}>
      <header className="dash-panel-head">
        <h3>{title}</h3>
        {subtitle ? <p className="dash-panel-sub">{subtitle}</p> : null}
      </header>
      {children}
    </section>
  );
}

function EmptyNote({ text }: { text: string }) {
  return <p className="dash-empty">{text}</p>;
}

/**
 * Ranked horizontal bars, one hue. Values are direct-labelled because the
 * length alone is unreadable once every bar is near the max.
 */
function RankedBars({
  rows,
  emptyText,
}: {
  rows: Array<{ key: string; label: string; value: number; note?: string }>;
  emptyText: string;
}) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  if (rows.length === 0) return <EmptyNote text={emptyText} />;
  return (
    <ul className="bar-list">
      {rows.map((row) => (
        <li key={row.key} className="bar-row">
          <span className="bar-row-label" title={row.label}>
            {row.label}
          </span>
          <span className="bar-row-track">
            <span
              className="bar-row-fill"
              style={{ inlineSize: `${(row.value / max) * 100}%` }}
            />
          </span>
          <span className="bar-row-value">
            {nf.format(row.value)}
            {row.note ? <span className="bar-row-note">{row.note}</span> : null}
          </span>
        </li>
      ))}
    </ul>
  );
}

/**
 * Acuity, the one chart that may not lean on colour. Each row states its
 * level number and clinical label; the stripe only reinforces them.
 */
function AcuityRows({
  rows,
  total,
  emptyText,
}: {
  rows: Array<{ level: number | null; count: number }>;
  total: number;
  emptyText: string;
}) {
  const { t } = useTranslation();
  if (total === 0) return <EmptyNote text={emptyText} />;
  const byLevel = new Map(rows.map((r) => [r.level ?? 0, r.count]));
  return (
    <ul className="acuity-list">
      {[1, 2, 3, 4, 5].map((level) => {
        const count = byLevel.get(level) ?? 0;
        const pct = total ? (count / total) * 100 : 0;
        return (
          <li key={level} className={`acuity-row ${count === 0 ? 'is-zero' : ''}`}>
            <span
              className="acuity-chip"
              style={{ background: LEVEL_TOKEN[level] }}
              aria-hidden="true"
            >
              {level}
            </span>
            <span className="acuity-name">{t(`triageLevelName_${level}`)}</span>
            <span className="acuity-track">
              <span className="acuity-fill" style={{ inlineSize: `${pct}%` }} />
            </span>
            <span className="acuity-count">{nf.format(count)}</span>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Today's arrivals, hour by hour. Dense 0-23 from SQL, so an empty hour is a
 * visible gap rather than a missing column that silently closes the spacing.
 */
function HourColumns({ rows, emptyText }: { rows: Array<{ hour: number; count: number }>; emptyText: string }) {
  const { t } = useTranslation();
  const max = Math.max(...rows.map((r) => r.count), 0);
  if (max === 0) return <EmptyNote text={emptyText} />;
  return (
    <div className="hour-chart">
      <ul className="hour-cols">
        {rows.map((row) => (
          <li key={row.hour} className="hour-col">
            <span
              className="hour-bar"
              style={{ blockSize: `${(row.count / max) * 100}%` }}
              title={t('dashHourTooltip', { hour: row.hour, n: row.count })}
            />
          </li>
        ))}
      </ul>
      <div className="hour-axis" aria-hidden="true">
        {[0, 6, 12, 18, 23].map((h) => (
          <span key={h} style={{ insetInlineStart: `${(h / 23) * 100}%` }}>
            {String(h).padStart(2, '0')}
          </span>
        ))}
      </div>
    </div>
  );
}

/**
 * Daily volume. One hue for screened patients over a recessive track for all
 * sessions started — the track is a background, not a second data series, so
 * there is no categorical palette to get wrong. Values are labelled because
 * the track fails the 3:1 contrast check on its own.
 */
function DailyColumns({
  rows,
  emptyText,
}: {
  rows: Array<{ date: string; sessions: number; screened: number }>;
  emptyText: string;
}) {
  const { t } = useTranslation();
  const max = Math.max(1, ...rows.map((r) => r.sessions));
  if (rows.every((r) => r.sessions === 0)) return <EmptyNote text={emptyText} />;
  return (
    <div className="daily-chart">
      <ul className="daily-cols">
        {rows.map((row) => (
          <li key={row.date} className="daily-col">
            <span className="daily-value">{row.sessions ? nf.format(row.sessions) : ''}</span>
            <span className="daily-track" style={{ blockSize: `${(row.sessions / max) * 100}%` }}>
              <span
                className="daily-fill"
                style={{ blockSize: row.sessions ? `${(row.screened / row.sessions) * 100}%` : '0%' }}
              />
            </span>
            <span className="daily-label">{row.date.slice(5)}</span>
          </li>
        ))}
      </ul>
      <ul className="chart-legend">
        <li>
          <span className="chart-key chart-key-fill" aria-hidden="true" />
          {t('dashLegendScreened')}
        </li>
        <li>
          <span className="chart-key chart-key-track" aria-hidden="true" />
          {t('dashLegendStarted')}
        </li>
      </ul>
    </div>
  );
}

export function TriageDashboard({ scope }: { scope: Scope }) {
  const { t } = useTranslation();
  const { language } = useLanguage();
  const formatDuration = useDuration();

  const [days, setDays] = useState<number>(7);
  const [stats, setStats] = useState<TriageStatsOut | null>(null);
  const [trends, setTrends] = useState<SurveillanceSummaryOut | null>(null);
  // Why the engine was overruled — the detail behind the agreement tile.
  // It used to sit under the working queue, unrelated to the work there.
  const [reroutes, setReroutes] = useState<RoutingFeedbackOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const [statsData, trendData, rerouteData] = await Promise.all([
          api.getTriageStats(days),
          api.getSurveillanceSummary(days),
          api.listRoutingFeedback().catch(() => [] as RoutingFeedbackOut[]),
        ]);
        if (cancelled) return;
        setStats(statsData);
        setTrends(trendData);
        setReroutes(rerouteData);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : t('error'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [days, t]);

  const acuityTotal = useMemo(
    () => (stats?.acuity ?? []).reduce((sum, row) => sum + row.count, 0),
    [stats],
  );

  const departmentRows = useMemo(
    () =>
      (stats?.departments ?? []).map((d) => ({
        key: d.code,
        label: (language === 'th' ? d.name_th : d.name_en) || d.name_en,
        value: d.count,
      })),
    [stats, language],
  );

  /**
   * Symptom counts, with the whole-utterance rows dropped.
   *
   * Two writers feed `symptom_keywords`: the extractor writes short English
   * terms, and the turn pipeline writes the free-text `symptoms_summary`. The
   * second kind arrived as sibling "symptoms" like a full Thai sentence, so a
   * ranked list was half sentences. Anything sentence-shaped is not a symptom
   * term and is filtered here rather than charted.
   */
  const symptomRows = useMemo(() => {
    const rising = new Map(
      (trends?.outbreak_alerts ?? []).map((a) => [a.keyword, a]),
    );
    return (trends?.top_symptoms ?? [])
      .filter(isSymptomTerm)
      .slice(0, 8)
      .map((s) => ({
        key: s.keyword,
        label: s.keyword,
        value: s.count,
        note: rising.has(s.keyword) ? t('dashRisingTag') : undefined,
      }));
  }, [trends, t]);

  const risingRows = useMemo(
    () =>
      (trends?.outbreak_alerts ?? []).filter((a) => isSymptomTerm(a)),
    [trends],
  );

  const agreement = stats?.agreement;
  const agreementPct =
    agreement?.agreement_rate === null || agreement?.agreement_rate === undefined
      ? null
      : Math.round(agreement.agreement_rate * 100);

  if (loading && !stats) return <p className="muted dash-loading">{t('loading')}</p>;

  if (error) {
    return (
      <p className="dash-error" role="alert">
        <WarningCircle size={18} weight="fill" aria-hidden="true" />
        {error}
      </p>
    );
  }

  return (
    <div className="dashboard">
      <div className="dash-toolbar">
        <div className="chip-group" role="group" aria-label={t('dashPeriod')}>
          {DAY_OPTIONS.map((option) => (
            <button
              key={option}
              type="button"
              className={`filter-chip ${days === option ? 'active' : ''}`}
              onClick={() => setDays(option)}
            >
              {t('dashLastDays', { n: option })}
            </button>
          ))}
        </div>
      </div>

      <div className="stat-row">
        <StatTile
          label={t('dashPendingReviews')}
          value={nf.format(stats?.pending_reviews ?? 0)}
          hint={
            stats?.oldest_pending_minutes != null
              ? t('dashOldestWait', { d: formatDuration(stats.oldest_pending_minutes) })
              : t('dashQueueClear')
          }
          tone={stats?.pending_reviews ? 'attention' : 'default'}
        />
        <StatTile
          label={t('dashScreenedWindow')}
          value={nf.format(acuityTotal)}
          hint={t('dashOverDays', { n: days })}
        />
        <StatTile
          label={t('dashAgreement')}
          value={agreementPct === null ? '—' : `${agreementPct}%`}
          hint={
            agreement && agreement.reviewed > 0
              ? t('dashAgreementHint', { n: agreement.rerouted })
              : t('dashNoReviewsYet')
          }
        />
        <StatTile
          label={t('dashAvgReviewTime')}
          value={formatDuration(agreement?.avg_review_minutes)}
          hint={t('dashAvgReviewHint')}
        />
      </div>

      <div className="dash-grid">
        <Panel title={t('dashAcuityTitle')} subtitle={t('dashAcuitySub')}>
          <AcuityRows
            rows={stats?.acuity ?? []}
            total={acuityTotal}
            emptyText={t('dashNoScreenings')}
          />
        </Panel>

        <Panel title={t('dashDepartmentTitle')} subtitle={t('dashDepartmentSub')}>
          <RankedBars rows={departmentRows} emptyText={t('dashNoRouting')} />
        </Panel>

        <Panel title={t('dashArrivalsTitle')} subtitle={t('dashArrivalsSub')}>
          <HourColumns rows={stats?.hourly_today ?? []} emptyText={t('dashNoArrivals')} />
        </Panel>

        <Panel title={t('dashSymptomsTitle')} subtitle={t('dashSymptomsSub', { n: days })}>
          <RankedBars rows={symptomRows} emptyText={t('dashNoSymptoms')} />
        </Panel>

        {risingRows.length > 0 && (
          <Panel title={t('dashRisingTitle')} subtitle={t('dashRisingSub')} wide>
            <ul className="rising-list">
              {risingRows.map((row) => (
                <li key={`${row.keyword}-${row.area}`} className="rising-row">
                  <ArrowUp size={16} weight="bold" aria-hidden="true" />
                  <span className="rising-keyword">{row.keyword}</span>
                  <span className="rising-counts">
                    {t('dashRisingCounts', {
                      now: row.recent_count,
                      before: row.previous_count,
                    })}
                  </span>
                  <span className="rising-delta">
                    {row.previous_count === 0
                      ? t('dashRisingNew')
                      : `+${Math.round(row.increase_pct)}%`}
                  </span>
                </li>
              ))}
            </ul>
            <p className="dash-footnote">
              <Minus size={14} aria-hidden="true" />
              {t('dashRisingFootnote')}
            </p>
          </Panel>
        )}

        {reroutes.length > 0 && (
          <Panel title={t('dashReroutesTitle')} subtitle={t('dashReroutesSub')} wide>
            <div className="table-wrap">
              <table className="staff-table">
                <thead>
                  <tr>
                    <th scope="col">{t('started')}</th>
                    <th scope="col">{t('department')}</th>
                    <th scope="col">{t('adminCorrectionReason')}</th>
                  </tr>
                </thead>
                <tbody>
                  {reroutes.slice(0, 8).map((row) => (
                    <tr key={row.id}>
                      <td>{new Date(row.created_at).toLocaleString()}</td>
                      <td>
                        {(language === 'th'
                          ? row.corrected_department_name_th ?? row.corrected_department_name_en
                          : row.corrected_department_name_en) ?? '—'}
                      </td>
                      <td>{row.reason ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        )}

        {scope === 'admin' && (
          <Panel title={t('dashVolumeTitle')} subtitle={t('dashVolumeSub')} wide>
            <DailyColumns rows={stats?.daily ?? []} emptyText={t('dashNoVolume')} />
          </Panel>
        )}
      </div>
    </div>
  );
}
