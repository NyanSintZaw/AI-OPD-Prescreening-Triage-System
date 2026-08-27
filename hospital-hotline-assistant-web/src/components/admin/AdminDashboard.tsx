/**
 * The administrator's dashboard.
 *
 * The admin portal used to mount `TriageDashboard` with `scope="admin"` — the
 * nurse's board plus a volume panel. That is the whole reason this file
 * exists, because the two roles are not asking a short and a long version of
 * one question:
 *
 *   Nurse  — "how sick are the people in front of me, and what is in my queue"
 *            Live, clinical, per-shift; every panel leads to a patient to open.
 *   Admin  — "did the booth work, and can I trust what it decided"
 *            Retrospective, operational, aggregate; nothing here is actionable
 *            on a single patient, and nothing here should be.
 *
 * Four bands, in the order an administrator actually asks them. Three of the
 * four have no counterpart on the nurse's board at all.
 *
 * The AI band is the largest single gain: `/admin/ai-metrics` has computed
 * call-site ok-rates, latency, validator violations and RAG grounding since
 * migration 014, and until now nothing in the frontend ever called it. The
 * validator catch count in particular is a *safety* number — it counts the
 * times a triage level, colour, diagnosis or prescription was stopped before
 * it reached a patient — and it has been invisible this whole time.
 *
 * Forms come from `../dashboard/charts`, which the nurse's board also uses, so
 * a department dot plot means the same thing in both portals. The rule that
 * file states — length is not the magnitude channel — is why nothing here is
 * a bar except the two forms that have earned it: the acuity share strip
 * (part-to-whole is what a stacked bar is for) and the meter (a ratio against
 * a limit the reader already knows).
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowUp, WarningCircle } from '@phosphor-icons/react';
import { api } from '../../api';
import type {
  AiMetricsOut,
  DailyVolume,
  RoutingFeedbackOut,
  SurveillanceSummaryOut,
  TriageStatsOut,
} from '../../api/types';
import { useLanguage } from '../../hooks/useSession';
import { useDuration } from '../../hooks/useDuration';
import { SelectField, type SelectOption } from '../ui/SelectField';
import {
  Band,
  DotPlot,
  EmptyNote,
  Figure,
  Funnel,
  Heatmap,
  Meter,
  Panel,
  ReasonList,
  ShareStrip,
  TrendArea,
  type HeatCell,
} from '../dashboard/charts';

const DAY_OPTIONS = [7, 14, 30] as const;
/* Four questions, four tabs. One scrolling page put the AI's safety record
   three screens below the fold, where nobody scrolls to find it; each tab is
   now a question an administrator arrives already asking. The band heading
   inside carries the full question — the tab label only has to be findable. */
const TABS = ['booth', 'ai', 'routing', 'demand'] as const;
type AdminBoardTab = (typeof TABS)[number];
const LEVELS = [1, 2, 3, 4, 5] as const;
/** Below this the engine is misbehaving rather than merely slow. */
const OK_RATE_FLOOR = 0.95;
const nf = new Intl.NumberFormat();

/**
 * Is this keyword a symptom term, or a whole utterance?
 *
 * Two writers feed `symptom_keywords`: the extractor writes short terms, and
 * the turn pipeline writes the free-text `symptoms_summary`. The second kind
 * arrives as a sibling "symptom" — a full Thai sentence ranked next to
 * "fever". Thai does not put spaces between words, so a word count cannot
 * tell the two apart; character length can.
 */
function isSymptomTerm({ keyword }: { keyword: string }): boolean {
  const term = keyword.trim();
  return term.length > 0 && term.length <= 24 && term.split(/\s+/).length <= 3;
}

const sum = (rows: DailyVolume[], get: (r: DailyVolume) => number) =>
  rows.reduce((acc, r) => acc + get(r), 0);

export function AdminDashboard() {
  const { t } = useTranslation();
  const { language } = useLanguage();
  const formatDuration = useDuration();

  const [days, setDays] = useState<number>(7);
  const [tab, setTab] = useState<AdminBoardTab>('booth');
  const [stats, setStats] = useState<TriageStatsOut | null>(null);
  // Only its `daily` array is read. Fetching double the window and keeping the
  // older half is what makes every delta a true period-over-period
  // comparison, rather than one half of the window the board is already
  // showing being compared against its other half.
  const [prior, setPrior] = useState<DailyVolume[]>([]);
  const [ai, setAi] = useState<AiMetricsOut | null>(null);
  const [trends, setTrends] = useState<SurveillanceSummaryOut | null>(null);
  const [reroutes, setReroutes] = useState<RoutingFeedbackOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const [statsData, doubleWindow, aiData, trendData, rerouteData] = await Promise.all([
          api.getTriageStats({ days }),
          api.getTriageStats({ days: Math.min(90, days * 2) }),
          // The board still works without the AI band; a missing audit table
          // must not blank the other three.
          api.getAiMetrics(days).catch(() => null),
          api.getSurveillanceSummary(days),
          api.listRoutingFeedback().catch(() => [] as RoutingFeedbackOut[]),
        ]);
        if (cancelled) return;
        setStats(statsData);
        setPrior(doubleWindow.daily.slice(0, Math.max(0, doubleWindow.daily.length - days)));
        setAi(aiData);
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

  const daily = useMemo(() => stats?.daily ?? [], [stats]);
  const funnel = stats?.funnel;

  const screened = sum(daily, (r) => r.screened);
  const started = sum(daily, (r) => r.sessions);
  const abandoned = started - screened;
  const priorStarted = sum(prior, (r) => r.sessions);
  const priorScreened = sum(prior, (r) => r.screened);

  const abandonPct = started > 0 ? Math.round((abandoned / started) * 100) : null;
  const priorAbandonPct =
    priorStarted > 0 ? Math.round(((priorStarted - priorScreened) / priorStarted) * 100) : null;

  const acuityTotal = useMemo(
    () => (stats?.acuity ?? []).reduce((acc, row) => acc + row.count, 0),
    [stats],
  );

  const agreement = stats?.agreement;
  const agreementPct =
    agreement?.agreement_rate == null ? null : Math.round(agreement.agreement_rate * 100);

  // Days the AI never ran contribute nothing, rather than a zero that would
  // drag the mean down and read as "fast".
  const latency = useMemo(() => {
    const withValue = daily.filter((r) => r.avg_latency_ms != null);
    if (withValue.length === 0) return null;
    return Math.round(sum(withValue, (r) => r.avg_latency_ms ?? 0) / withValue.length);
  }, [daily]);

  const escalations = sum(daily, (r) => r.escalated);

  const departmentRows = useMemo(
    () =>
      (stats?.departments ?? []).map((d) => ({
        key: d.code,
        label: (language === 'th' ? d.name_th : d.name_en) || d.name_en,
        value: d.count,
      })),
    [stats, language],
  );

  const symptomRows = useMemo(() => {
    const rising = new Set((trends?.outbreak_alerts ?? []).map((a) => a.keyword));
    return (trends?.top_symptoms ?? [])
      .filter(isSymptomTerm)
      .slice(0, 8)
      .map((s) => ({
        key: s.keyword,
        label: rising.has(s.keyword) ? `${s.keyword} · ${t('dashRisingTag')}` : s.keyword,
        value: s.count,
      }));
  }, [trends, t]);

  // Terms moving faster than their own baseline. Neutral wording throughout —
  // this is a trend, and the board never calls it anything stronger.
  const risingRows = useMemo(
    () => (trends?.outbreak_alerts ?? []).filter((a) => isSymptomTerm(a)),
    [trends],
  );

  /**
   * Proposed department × nurse-confirmed department.
   *
   * "Agreement was 87%" is not something an administrator can do anything
   * with. This says *which pairs* the engine confuses, and a confused pair is
   * a criteria edit. Restricted to departments that appear in a reroute, so
   * the grid is not mostly empty rows for departments nobody ever argued
   * about.
   */
  const confusion = useMemo(() => {
    const name = (en: string | null, th: string | null) =>
      ((language === 'th' ? th : en) || en || th || '').trim();
    const pairs = reroutes
      .map((r) => ({
        from: name(r.original_department_name_en, r.original_department_name_th),
        to: name(r.corrected_department_name_en, r.corrected_department_name_th),
      }))
      .filter((p) => p.from && p.to);
    if (pairs.length === 0) return null;
    const rows = [...new Set(pairs.map((p) => p.from))].sort();
    const cols = [...new Set(pairs.map((p) => p.to))].sort();
    const counts = new Map<string, number>();
    pairs.forEach((p) => {
      const key = `${rows.indexOf(p.from)}:${cols.indexOf(p.to)}`;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    });
    const cells: HeatCell[] = [...counts.entries()].map(([key, value]) => {
      const [row, col] = key.split(':').map(Number);
      return { row, col, value };
    });
    return { rows, cols, cells };
  }, [reroutes, language]);

  const weekdayCells = useMemo<HeatCell[]>(
    () =>
      (stats?.weekday_hourly ?? []).map((c) => ({ row: c.weekday, col: c.hour, value: c.count })),
    [stats],
  );
  const busiestHour = Math.max(0, ...weekdayCells.map((c) => c.value));

  // 0 = Sunday, matching Postgres EXTRACT(DOW), which is what the API returns.
  const weekdayLabels = useMemo(() => [0, 1, 2, 3, 4, 5, 6].map((d) => t(`dashWeekday_${d}`)), [t]);
  const hourLabels = useMemo(
    () => Array.from({ length: 24 }, (_, h) => String(h).padStart(2, '0')),
    [],
  );

  const grounding = ai?.grounding;
  const violations = ai?.validator_violations ?? [];
  const violationTotal = violations.reduce((acc, v) => acc + v.count, 0);

  const periodOptions: SelectOption[] = DAY_OPTIONS.map((n) => ({
    value: String(n),
    label: t('dashLastDays', { n }),
  }));

  const deltaOf = (now: number, before: number) =>
    prior.length === 0 || before === 0
      ? null
      : {
          text: t('dashVsPrev', { n: days, delta: nf.format(Math.abs(now - before)) }),
          up: now === before ? null : now > before,
        };

  if (loading && !stats) return <p className="muted dash-loading">{t('loading')}</p>;

  if (error) {
    return (
      <p className="dash-error" role="alert">
        <WarningCircle size={18} weight="duotone" aria-hidden="true" />
        {error}
      </p>
    );
  }

  return (
    <div className="dashboard admin-dashboard">
      {/* One period control for the whole board, not one per tab — switching
          tabs must not silently change the window you are reading. It rides
          the tab row so it is visible from every tab. */}
      <div className="dash-tabbar">
        <div className="tabs" role="tablist">
          {TABS.map((id) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              className={`tab ${tab === id ? 'active' : ''}`}
              onClick={() => setTab(id)}
            >
              {t(`dashTab_${id}`)}
            </button>
          ))}
        </div>
        <SelectField
          value={String(days)}
          options={periodOptions}
          onChange={(v) => setDays(Number(v))}
          aria-label={t('dashPeriod')}
          className="dash-period-select"
        />
      </div>

      {/* ── 1 · Did the booth work ──────────────────────────────────────── */}
      {tab === 'booth' && (
        <Band title={t('dashBandBooth')} note={t('dashBandBoothNote')}>
          <div className="dash-figures">
            <Figure
              tile
              hero
              label={t('dashHeroLabel')}
              value={nf.format(screened)}
              delta={deltaOf(screened, priorScreened)}
              spark={{
                values: daily.map((r) => r.screened),
                label: t('dashHeroSparkLabel', { n: days }),
              }}
              hint={t('dashOverDays', { n: days })}
            />
            <Figure
              tile
              label={t('dashStarted')}
              value={nf.format(started)}
              delta={deltaOf(started, priorStarted)}
              spark={{ values: daily.map((r) => r.sessions), label: t('dashStartedSparkLabel') }}
              hint={t('dashStartedHint')}
            />
            <Figure
              tile
              label={t('dashAbandonRate')}
              value={abandonPct === null ? '—' : String(abandonPct)}
              unit={abandonPct === null ? undefined : '%'}
              delta={
                abandonPct !== null && priorAbandonPct !== null
                  ? deltaOf(abandonPct, priorAbandonPct)
                  : null
              }
              spark={{
                values: daily.map((r) =>
                  r.sessions ? Math.round(((r.sessions - r.screened) / r.sessions) * 100) : 0,
                ),
                label: t('dashAbandonSparkLabel'),
              }}
              hint={t('dashAbandonHint', { n: abandoned })}
              tone={abandonPct !== null && abandonPct >= 40 ? 'attention' : undefined}
            />
            <Figure
              tile
              label={t('dashAvgLatency')}
              value={latency === null ? '—' : nf.format(latency)}
              unit={latency === null ? undefined : 'ms'}
              spark={{
                values: daily.map((r) => r.avg_latency_ms ?? 0),
                label: t('dashLatencySparkLabel'),
              }}
              hint={t('dashLatencyHint')}
            />
          </div>

          <Panel title={t('dashFunnelTitle')} subtitle={t('dashFunnelSub')} span={3}>
            {funnel && funnel.started > 0 ? (
              <>
                <Funnel
                  // Order follows the pipeline, not the org chart. The stage-1
                  // HIS push fires at disposition — before a nurse has seen
                  // anything — so review is the LAST stage, not the third. The
                  // other order rendered 3 -> 0 -> 2 and broke the panel's own
                  // "each stage is a subset of the one before it".
                  //
                  // Each drop is worded here rather than drawn as "−2", because
                  // the three are not the same event: one is a patient who
                  // walked away, one is a record the HIS did not take, and the
                  // last is work a nurse has not reached yet — which is not a
                  // loss at all and must not read like one.
                  stages={[
                    { key: 'started', label: t('dashFunnelStarted'), value: funnel.started },
                    {
                      key: 'disposed',
                      label: t('dashFunnelDisposed'),
                      value: funnel.disposed,
                      drop:
                        funnel.started > funnel.disposed
                          ? t('dashFunnelDropDisposed', { n: funnel.started - funnel.disposed })
                          : undefined,
                    },
                    {
                      key: 'pushed',
                      label: t('dashFunnelPushed'),
                      value: funnel.his_pushed,
                      drop:
                        funnel.disposed > funnel.his_pushed
                          ? t('dashFunnelDropPushed', { n: funnel.disposed - funnel.his_pushed })
                          : undefined,
                      note:
                        funnel.his_failed || funnel.his_skipped
                          ? t('dashFunnelHisNote', {
                              failed: funnel.his_failed,
                              skipped: funnel.his_skipped,
                            })
                          : undefined,
                    },
                    {
                      key: 'reviewed',
                      label: t('dashFunnelReviewed'),
                      value: funnel.reviewed,
                      drop:
                        funnel.his_pushed > funnel.reviewed
                          ? t('dashFunnelDropReviewed', { n: funnel.his_pushed - funnel.reviewed })
                          : undefined,
                    },
                  ]}
                />
                <p className="dash-footnote">{t('dashFunnelFootnote')}</p>
              </>
            ) : (
              <EmptyNote text={t('dashNoVolume')} />
            )}
          </Panel>
        </Band>
      )}

      {/* ── 2 · Can I trust the AI ──────────────────────────────────────── */}
      {tab === 'ai' && (
        <Band title={t('dashBandAi')} note={t('dashBandAiNote')}>
          <Panel title={t('dashCallSitesTitle')} subtitle={t('dashCallSitesSub')} span={2}>
            {/* A table, not a chart. Four call sites carrying three measures
                each is past the point where colour classes stay apart, and an
                administrator reads these as numbers anyway. */}
            {ai && ai.call_sites.length > 0 ? (
              <div className="table-wrap scroll-slim">
                <table className="staff-table dash-table">
                  <thead>
                    <tr>
                      <th scope="col">{t('dashCallSite')}</th>
                      <th scope="col" className="num">{t('dashCalls')}</th>
                      <th scope="col" className="num">{t('dashOkRate')}</th>
                      <th scope="col" className="num">{t('dashLatency')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ai.call_sites.map((cs) => (
                      <tr key={cs.call_site}>
                        <td>{t(`dashCallSite_${cs.call_site}`, { defaultValue: cs.call_site })}</td>
                        <td className="num">{nf.format(cs.calls)}</td>
                        <td
                          className={`num ${
                            cs.ok_rate !== null && cs.ok_rate < OK_RATE_FLOOR ? 'is-bad' : ''
                          }`}
                        >
                          {cs.ok_rate === null ? '—' : `${Math.round(cs.ok_rate * 100)}%`}
                        </td>
                        <td className="num">
                          {cs.avg_latency_ms === null
                            ? '—'
                            : `${nf.format(cs.avg_latency_ms)} ms`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyNote text={t('dashNoAiMetrics')} />
            )}
          </Panel>

          <Panel title={t('dashGroundingTitle')} subtitle={t('dashGroundingSub')}>
            {grounding && grounding.explanations > 0 ? (
              <>
                <Meter
                  label={t('dashGroundedExplanations')}
                  value={grounding.grounded}
                  total={grounding.explanations}
                  tone={
                    grounding.grounded_rate !== null && grounding.grounded_rate < 0.5
                      ? 'warning'
                      : 'default'
                  }
                />
                {grounding.ungrounded_reasons.length > 0 ? (
                  <ReasonList
                    rows={grounding.ungrounded_reasons.map((r) => ({
                      key: r.reason,
                      label: t(`nurseUngroundedReason_${r.reason}`, { defaultValue: r.reason }),
                      value: r.count,
                    }))}
                  />
                ) : null}
                <p className="dash-footnote">{t('dashGroundingFootnote')}</p>
              </>
            ) : (
              <EmptyNote text={t('dashNoAiMetrics')} />
            )}
          </Panel>

          <Panel title={t('dashSafetyTitle')} subtitle={t('dashSafetySub')} span={3}>
            {/* The validator is what stops a triage level, a colour, a diagnosis
                or a prescription reaching a patient. Its catch count is a safety
                number, and no surface showed it before this one. */}
            <div className="dash-figures">
              <Figure
                label={t('dashViolationsCaught')}
                value={nf.format(violationTotal)}
                hint={t('dashViolationsHint')}
                tone={violationTotal > 0 ? 'attention' : undefined}
              />
              <Figure
                label={t('dashEscalations')}
                value={nf.format(escalations)}
                spark={{
                  values: daily.map((r) => r.escalated),
                  label: t('dashEscalationSparkLabel'),
                }}
                hint={t('dashEscalationHint')}
              />
            </div>
            {violations.length > 0 ? (
              <ReasonList
                rows={violations.map((v) => ({
                  key: v.violation,
                  label: t(`dashViolation_${v.violation}`, { defaultValue: v.violation }),
                  value: v.count,
                }))}
              />
            ) : (
              <p className="dash-footnote">{t('dashSafetyFootnote')}</p>
            )}
          </Panel>
        </Band>
      )}

      {/* ── 3 · Is the routing right ────────────────────────────────────── */}
      {tab === 'routing' && (
        <Band title={t('dashBandRouting')} note={t('dashBandRoutingNote')}>
          <div className="dash-figures">
            <Figure
              tile
              label={t('dashAgreement')}
              value={agreementPct === null ? '—' : String(agreementPct)}
              unit={agreementPct === null ? undefined : '%'}
              spark={{
                values: daily.map((r) =>
                  r.reviewed ? Math.round(((r.reviewed - r.rerouted) / r.reviewed) * 100) : 0,
                ),
                label: t('dashAgreementSparkLabel'),
              }}
              hint={
                agreement && agreement.reviewed > 0
                  ? t('dashAgreementHint', { n: agreement.rerouted })
                  : t('dashNoReviewsYet')
              }
            />
            <Figure
              tile
              label={t('dashReviewed')}
              value={nf.format(agreement?.reviewed ?? 0)}
              spark={{ values: daily.map((r) => r.reviewed), label: t('dashReviewedSparkLabel') }}
              hint={t('dashReviewedHint')}
            />
            <Figure
              tile
              label={t('dashAvgReviewTime')}
              value={formatDuration(agreement?.avg_review_minutes)}
              hint={t('dashAvgReviewHint')}
            />
            <Figure
              tile
              label={t('dashPendingReviews')}
              value={nf.format(stats?.pending_reviews ?? 0)}
              hint={
                stats?.oldest_pending_minutes != null
                  ? `${t('dashLongestWait')} · ${formatDuration(stats.oldest_pending_minutes)}`
                  : t('dashQueueClear')
              }
              tone={stats?.pending_reviews ? 'attention' : undefined}
            />
          </div>

          <Panel title={t('dashAcuityTitle')} subtitle={t('dashAcuitySub')}>
            {acuityTotal === 0 ? (
              <EmptyNote text={t('dashNoScreenings')} />
            ) : (
              <ShareStrip
                total={acuityTotal}
                rows={LEVELS.map((level) => ({
                  level,
                  name: t(`triageLevelName_${level}`),
                  count: (stats?.acuity ?? []).find((a) => a.level === level)?.count ?? 0,
                }))}
              />
            )}
          </Panel>

          <Panel title={t('dashConfusionTitle')} subtitle={t('dashConfusionSub')} span={2}>
            {confusion ? (
              <>
                <Heatmap
                  cells={confusion.cells}
                  rowLabels={confusion.rows}
                  colLabels={confusion.cols}
                  maxLabel={(max) => nf.format(max)}
                  cellLabel={(r, c, v) =>
                    t('dashConfusionCell', { from: confusion.rows[r], to: confusion.cols[c], n: v })
                  }
                />
                <p className="dash-footnote">{t('dashConfusionFootnote')}</p>
              </>
            ) : (
              <EmptyNote text={t('dashNoReroutes')} />
            )}
          </Panel>
        </Band>
      )}

      {/* ── 4 · What is the demand ──────────────────────────────────────── */}
      {tab === 'demand' && (
        <Band title={t('dashBandDemand')} note={t('dashBandDemandNote')}>
          <Panel title={t('dashVolumeTitle')} subtitle={t('dashVolumeSub')} span={3}>
            {daily.length < 2 ? (
              <EmptyNote text={t('dashNoVolume')} />
            ) : (
              <TrendArea
                points={daily.map((r) => ({ tick: r.date.slice(5), value: r.screened }))}
                // Today is still being written, so the last settled slot is
                // yesterday — today is drawn pending rather than as a day that
                // dipped.
                liveUntil={daily.length - 2}
                tickEvery={Math.ceil(daily.length / 7)}
                label={t('dashVolumeAria', {
                  list: daily.map((r) => `${r.date.slice(5)} ${r.screened}`).join(', '),
                })}
                formatPoint={(p) => t('dashVolumePoint', { date: p.tick, n: p.value })}
              />
            )}
          </Panel>

          <Panel title={t('dashRhythmTitle')} subtitle={t('dashRhythmSub', { n: days })} span={3}>
            {busiestHour === 0 ? (
              <EmptyNote text={t('dashNoArrivals')} />
            ) : (
              <>
                <Heatmap
                  cells={weekdayCells}
                  rowLabels={weekdayLabels}
                  colLabels={hourLabels}
                  colTick={3}
                  maxLabel={(max) => nf.format(max)}
                  cellLabel={(r, c, v) =>
                    t('dashRhythmCell', { day: weekdayLabels[r], hour: hourLabels[c], n: v })
                  }
                />
                <p className="dash-footnote">{t('dashRhythmFootnote')}</p>
              </>
            )}
          </Panel>

          <Panel title={t('dashDepartmentTitle')} subtitle={t('dashDepartmentSub')}>
            {departmentRows.length === 0 ? (
              <EmptyNote text={t('dashNoRouting')} />
            ) : (
              <DotPlot rows={departmentRows} axisLabel={t('dashDeptAxis')} />
            )}
          </Panel>

          <Panel title={t('dashSymptomsTitle')} subtitle={t('dashSymptomsSub', { n: days })}>
            {symptomRows.length === 0 ? (
              <EmptyNote text={t('dashNoSymptoms')} />
            ) : (
              <DotPlot rows={symptomRows} axisLabel={t('dashSymptomAxis')} />
            )}
          </Panel>

          {risingRows.length > 0 ? (
            <Panel title={t('dashRisingTitle')} subtitle={t('dashRisingSub')} span={3}>
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
              <p className="dash-footnote">{t('dashRisingFootnote')}</p>
            </Panel>
          ) : null}
        </Band>
      )}
    </div>
  );
}
