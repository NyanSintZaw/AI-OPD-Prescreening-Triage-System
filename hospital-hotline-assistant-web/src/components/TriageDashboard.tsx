/**
 * The one dashboard, mounted in both staff portals.
 *
 * It reads top-to-bottom as urgency decays — **right now**, then **today**,
 * then **the period** — because the old flat grid of eight equal panels made
 * the nurse hunt for the one thing that needed her: a 5-day-old unconfirmed
 * screening sat in a small tile between symptom frequencies.
 *
 *  - **Right now** is unscoped and live: who is waiting, how sick, how long.
 *    It is the only band a nurse needs before she has had coffee.
 *  - **Today** is the booth's shift: how many screened, when they arrived.
 *  - **The period** (7/14/30) is the only band the toolbar scopes, and it says
 *    so — the old toolbar silently didn't apply to "arrivals today".
 *
 * Volume across the window, symptom frequency and the AI's own record live on
 * the administrator's board instead (`components/admin/AdminDashboard.tsx`).
 * They are deliberately **not** here — a nurse cannot act on a 30-day symptom
 * rank, and the underlying `symptom_keywords` mixes chief complaints with
 * history and allergies, so "coronary artery disease" ranks beside "fever".
 *
 * Forms are chosen in `dashboard/charts.tsx`; the rule that governs them is
 * that length stopped being the magnitude channel. See that file.
 */
import { useEffect, useLayoutEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { ArrowRight, WarningCircle } from '@phosphor-icons/react';
import { api } from '../api';
import type {
  AssessmentReviewOut,
  RoutingFeedbackOut,
  TriageStatsOut,
} from '../api/types';
import { useLanguage } from '../hooks/useSession';
import { useDuration } from '../hooks/useDuration';
import { TriageBadge } from './staff/TriageBadge';
import { DateRangeField, type DateRange } from './ui/DateRangeField';
import { daysBetween, fromDateValue } from './ui/dateRange';
import {
  Band,
  DotPlot,
  EmptyNote,
  Figure,
  Panel,
  ShareStrip,
  TrendArea,
  UnitStrip,
  type DotRow,
  type TrendPoint,
  type Unit,
} from './dashboard/charts';

const DAY_OPTIONS = [7, 14, 30] as const;

/** The hour band the arrivals chart always draws, widened by any real
 *  reading outside it. A fixed 0–23 spent ten columns on hours the booth is
 *  shut; a purely data-driven window would jump about between refreshes. */
/* How long a screening may sit unconfirmed before the board calls it out.
   Two hours, because the booth is a same-visit flow — the patient is meant to
   be seen on this trip, not called back. Not a clinical SLA and not presented
   as one; it is the line at which the board stops assuming someone is on it.
   ponytail: one constant, per-level thresholds if a clinician wants them. */
const STALE_MINUTES = 120;

/** Past this the list stops being scannable and starts being the queue table
 *  the nurse already has a tab for. The overflow is counted, never hidden. */
const ATTENTION_CAP = 5;

const CLINIC_FROM = 7;
const CLINIC_TO = 19;

const nf = new Intl.NumberFormat();

/**
 * The page header's actions slot, once it exists.
 *
 * The period toolbar belongs on the title's line — the header is already a
 * `space-between` row built for exactly this, and giving the toolbar a row of
 * its own meant a full-width band with content in the right third and nothing
 * in the other two. A portal rather than lifting the period state into the
 * page: the state belongs to the board, only its pixels belong up there.
 *
 * `useLayoutEffect` so the toolbar is placed before paint. With a passive
 * effect it renders once without and appears on the next frame, which reads as
 * the header flickering on every visit.
 */
function usePortalTarget(id: string): HTMLElement | null {
  const [node, setNode] = useState<HTMLElement | null>(null);
  useLayoutEffect(() => {
    setNode(document.getElementById(id));
  });
  return node;
}

function minutesSince(iso: string): number {
  return Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
}

/* ── Shells ───────────────────────────────────────────────────────────── */

/* ── The board ────────────────────────────────────────────────────────── */

export function TriageDashboard({
  /** Present only where there is a queue to open — the nurse portal. */
  onOpenQueue,
}: {
  onOpenQueue?: () => void;
}) {
  const { t } = useTranslation();
  const { language } = useLanguage();
  const formatDuration = useDuration();
  const headSlot = usePortalTarget('staff-head-actions');

  /**
   * The period, and which control set it.
   *
   * One piece of state rather than two, because the board can only show one
   * window: picking dates has to clear the active chip and picking a chip has
   * to clear the dates, or the toolbar would claim two answers at once.
   */
  const [range, setRange] = useState<DateRange | null>(null);
  const [rollingDays, setRollingDays] = useState<number>(7);

  /** What the band heading and the sub-copy count in — the chips' own number,
   *  or the length of the chosen range. */
  const days = useMemo(() => {
    if (!range) return rollingDays;
    const from = fromDateValue(range.from);
    const to = fromDateValue(range.to);
    return from && to ? daysBetween(from, to) : rollingDays;
  }, [range, rollingDays]);
  const [stats, setStats] = useState<TriageStatsOut | null>(null);
  const [pending, setPending] = useState<AssessmentReviewOut[]>([]);
  // Why the engine was overruled — the detail behind the agreement figure.
  const [reroutes, setReroutes] = useState<RoutingFeedbackOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        // Surveillance is no longer fetched here — symptom frequency moved to
        // the administrator's board, and this was a round trip whose result
        // the nurse never saw.
        const [statsData, pendingData, rerouteData] = await Promise.all([
          api.getTriageStats(range ?? { days: rollingDays }),
          // The one call the stats endpoint cannot stand in for: it returns a
          // pending *count*, and the question this board leads with is which
          // levels are in that count and how long the worst has waited.
          api.listAssessmentReviews('pending').catch(() => [] as AssessmentReviewOut[]),
          api.listRoutingFeedback().catch(() => [] as RoutingFeedbackOut[]),
        ]);
        if (cancelled) return;
        setStats(statsData);
        setPending(pendingData);
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
    // `t` is deliberately not a dependency: it is only read for an error
    // message, and its identity changes on every language switch — which was
    // refetching the whole board to render the same numbers in Thai.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range, rollingDays]);

  /* ── Right now ─────────────────────────────────────────────────────── */

  /** Sickest first, then longest-waiting — the order a nurse would pick them
   *  up in, which is what makes the strip readable as a queue and not a bag. */
  const waiting: Unit[] = useMemo(
    () =>
      [...pending]
        .sort(
          (a, b) =>
            (a.triage_level ?? 9) - (b.triage_level ?? 9) ||
            new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
        )
        .map((row) => ({
          id: row.assessment_id,
          level: row.triage_level,
          label: t('dashWaitingUnit', {
            name: row.patient_name || row.patient_hn || t('dashWaitingAnon'),
            level: row.triage_level ?? '—',
            d: formatDuration(minutesSince(row.created_at)),
          }),
        })),
    [pending, t, formatDuration],
  );

  /**
   * What is wrong with a waiting case, if anything.
   *
   * The board could tell a nurse how many were waiting and how sick they were,
   * and nothing else — so acting on any of it meant leaving for the queue and
   * finding the row again. Every dashboard worth copying puts the exceptions
   * on the board itself; this is that list, and it costs no extra request
   * because the pending reviews were already loaded for the count.
   *
   * Ordered by what a nurse would pick up first, not by how many flags a row
   * collected: an unconfirmed level 2 outranks a level 5 with three notes.
   */
  const flagsFor = (row: AssessmentReviewOut): { stale: boolean; reasons: string[] } => {
    const out: string[] = [];
    const level = row.triage_level ?? 9;
    // Staleness is not written into the reasons: the row already ends with the
    // elapsed time, and "Waiting 5 d 8 h · 5 d 8 h" is what that produced. It
    // colours that column instead, so the number does one job and says two
    // things.
    const stale = minutesSince(row.created_at) >= STALE_MINUTES;
    if (level <= 2) out.push(t('dashFlagUrgent', { level }));
    if (row.missing_vitals?.length) {
      out.push(
        t('dashFlagVitals', {
          list: row.missing_vitals
            .map((k) => t(`nurseMissingVitalName_${k}`, { defaultValue: k }))
            .join(', '),
        }),
      );
    }
    if (row.rejected_vitals && Object.keys(row.rejected_vitals).length > 0) {
      out.push(t('dashFlagRejected'));
    }
    if (row.patient_contact_requested) out.push(t('dashFlagCallback'));
    return { stale, reasons: out };
  };

  const attention = useMemo(
    () =>
      pending
        .map((row) => ({ row, ...flagsFor(row) }))
        .filter((entry) => entry.stale || entry.reasons.length > 0)
        .sort(
          (a, b) =>
            (a.row.triage_level ?? 9) - (b.row.triage_level ?? 9) ||
            new Date(a.row.created_at).getTime() - new Date(b.row.created_at).getTime(),
        ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [pending, t, formatDuration],
  );

  const pendingCount = stats?.pending_reviews ?? pending.length;

  /* ── Today ─────────────────────────────────────────────────────────── */

  const daily = stats?.daily ?? [];
  const today = daily.length ? daily[daily.length - 1] : null;
  const priorDays = daily.slice(0, -1);
  const priorMean = priorDays.length
    ? priorDays.reduce((sum, r) => sum + r.screened, 0) / priorDays.length
    : null;
  const screenedDelta =
    today && priorMean !== null ? Math.round(today.screened - priorMean) || 0 : null;

  const arrivals: TrendPoint[] = useMemo(() => {
    const rows = stats?.hourly_today ?? [];
    const busy = rows.filter((r) => r.count > 0).map((r) => r.hour);
    // Widened, never narrowed, by real readings: a 05:00 walk-in must not be
    // cropped out of the chart just because the booth normally opens at 07.
    const from = Math.min(CLINIC_FROM, ...busy);
    const to = Math.max(CLINIC_TO, ...busy);
    const byHour = new Map(rows.map((r) => [r.hour, r.count]));
    const out: TrendPoint[] = [];
    for (let hour = from; hour <= to; hour += 1) {
      out.push({ tick: `${String(hour).padStart(2, '0')}`, value: byHour.get(hour) ?? 0 });
    }
    return out;
  }, [stats]);

  const arrivalsLiveUntil = useMemo(() => {
    const rows = stats?.hourly_today ?? [];
    const busy = rows.filter((r) => r.count > 0).map((r) => r.hour);
    const from = Math.min(CLINIC_FROM, ...busy);
    return new Date().getHours() - from;
  }, [stats]);

  const arrivalsTotal = arrivals.reduce((sum, p) => sum + p.value, 0);

  const peakHour = useMemo(
    () => arrivals.reduce<TrendPoint | null>((best, p) => (!best || p.value > best.value ? p : best), null),
    [arrivals],
  );

  /* ── The period ────────────────────────────────────────────────────── */

  const acuityTotal = useMemo(
    () => (stats?.acuity ?? []).reduce((sum, row) => sum + row.count, 0),
    [stats],
  );

  const acuityShares = useMemo(() => {
    const byLevel = new Map((stats?.acuity ?? []).map((r) => [r.level ?? 0, r.count]));
    return [1, 2, 3, 4, 5].map((level) => ({
      level,
      name: t(`triageLevelName_${level}`),
      count: byLevel.get(level) ?? 0,
    }));
  }, [stats, t]);

  const departmentRows: DotRow[] = useMemo(
    () =>
      (stats?.departments ?? []).map((d) => ({
        key: d.code,
        label: (language === 'th' ? d.name_th : d.name_en) || d.name_en,
        value: d.count,
      })),
    [stats, language],
  );

  const agreement = stats?.agreement;
  const agreementPct =
    agreement?.agreement_rate === null || agreement?.agreement_rate === undefined
      ? null
      : Math.round(agreement.agreement_rate * 100);

  /** Reroutes folded to "where nurses moved patients to, and how often" — the
   *  raw feed was eight timestamped rows, which answered no question. */
  const rerouteTargets = useMemo(() => {
    const tally = new Map<string, number>();
    reroutes.forEach((row) => {
      const name =
        (language === 'th'
          ? row.corrected_department_name_th ?? row.corrected_department_name_en
          : row.corrected_department_name_en) ?? '—';
      tally.set(name, (tally.get(name) ?? 0) + 1);
    });
    return [...tally.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);
  }, [reroutes, language]);

  if (loading && !stats) return <p className="muted dash-loading">{t('loading')}</p>;

  if (error) {
    return (
      <p className="dash-error" role="alert">
        <WarningCircle size={18} weight="duotone" aria-hidden="true" />
        {error}
      </p>
    );
  }

  const toolbar = (
  <div className="dash-toolbar">
      <span className="dash-toolbar-label" id="dash-period-label">
        {t('dashPeriod')}
      </span>
      <div className="chip-group" role="group" aria-labelledby="dash-period-label">
        {DAY_OPTIONS.map((option) => (
          <button
            key={option}
            type="button"
            className={`filter-chip ${!range && rollingDays === option ? 'active' : ''}`}
            onClick={() => {
              setRollingDays(option);
              setRange(null);
            }}
          >
            {t('dashLastDays', { n: option })}
          </button>
        ))}
      </div>
    <DateRangeField value={range} onChange={setRange} label={t('dashPickDatesLabel')} />
  </div>
  );

  return (
    <div className="dashboard">
      {/* Into the page header when there is one, in place otherwise — the
          board is mounted in more than one shell. */}
      {headSlot ? createPortal(toolbar, headSlot) : toolbar}

      <Band title={t('dashBandNow')}>
        {/* Two panels, not one across the row: the queue and its worst case
            are two readings, and holding both in a single full-width card
            left a metre of empty white between them. */}
        <Panel
          title={t('dashWaitingTitle')}
          subtitle={t('dashWaitingSub')}
        >
          {pendingCount === 0 ? (
            <p className="dash-clear">{t('dashQueueClear')}</p>
          ) : (
            <>
              <div className="waiting">
                <Figure hero value={nf.format(pendingCount)} unit={t('dashWaitingUnitWord')} />
                <UnitStrip
                  units={waiting}
                  onSelect={onOpenQueue ? () => onOpenQueue() : undefined}
                />
              </div>
              {onOpenQueue ? (
                <button type="button" className="dash-panel-action" onClick={onOpenQueue}>
                  {t('dashOpenQueue')}
                  <ArrowRight size={15} weight="bold" aria-hidden="true" />
                </button>
              ) : null}
            </>
          )}
        </Panel>

        {/* The exceptions, as rows. A count and a strip of level chips say how
            many and how sick; they cannot say *who*, so acting on any of it
            meant leaving the board. This is the one panel a nurse can work
            from. The longest wait used to be its own tile — it is a flag like
            any other and belongs in the list rather than beside it. */}
        <Panel title={t('dashAttentionTitle')} subtitle={t('dashAttentionSub')} span={2}>
          {attention.length === 0 ? (
            <p className="dash-clear">
              {pendingCount === 0 ? t('dashQueueClear') : t('dashAttentionClear')}
            </p>
          ) : (
            <ul className="attention-list">
              {attention.slice(0, ATTENTION_CAP).map(({ row, stale, reasons }) => {
                const name = row.patient_name || row.patient_hn || t('dashWaitingAnon');
                const Row = onOpenQueue ? 'button' : 'div';
                return (
                  <li key={row.assessment_id}>
                    <Row
                      {...(onOpenQueue
                        ? { type: 'button' as const, onClick: onOpenQueue }
                        : {})}
                      className="attention-row"
                    >
                      <TriageBadge level={row.triage_level} />
                      <span className="attention-who">{name}</span>
                      <span className="attention-why">{reasons.join(' · ')}</span>
                      <span className={`attention-wait ${stale ? 'is-stale' : ''}`}>
                        {formatDuration(minutesSince(row.created_at))}
                      </span>
                      {onOpenQueue ? (
                        <ArrowRight size={14} weight="bold" aria-hidden="true" />
                      ) : null}
                    </Row>
                  </li>
                );
              })}
              {attention.length > ATTENTION_CAP ? (
                <li className="attention-more">
                  {t('dashAttentionMore', { n: attention.length - ATTENTION_CAP })}
                </li>
              ) : null}
            </ul>
          )}
        </Panel>

        <Panel title={t('dashScreenedToday')} subtitle={t('dashScreenedTodaySub', { n: days })}>
          <Figure
            value={nf.format(today?.screened ?? 0)}
            delta={
              screenedDelta === null
                ? null
                : {
                    // "0 against the 7-day average" is a sentence that says
                    // nothing; on the day it is true, say it in words.
                    text:
                      screenedDelta === 0
                        ? t('dashSameAsAverage', { n: days })
                        : t('dashVsAverage', {
                            delta: `${screenedDelta > 0 ? '+' : ''}${nf.format(screenedDelta)}`,
                            n: days,
                          }),
                    up: screenedDelta === 0 ? null : screenedDelta > 0,
                  }
            }
            spark={{
              values: daily.map((r) => r.screened),
              label: t('dashSparkLabel', { n: days }),
            }}
          />
        </Panel>

        <Panel title={t('dashArrivalsTitle')} subtitle={t('dashArrivalsSub')} span={2}>
          {arrivalsTotal === 0 ? (
            <EmptyNote text={t('dashNoArrivals')} />
          ) : (
            <>
              {/* The card's own summary, on the card — a chart whose total is
                  only in the subtitle makes the reader add up the shape. */}
              <div className="chart-head">
                <Figure value={nf.format(arrivalsTotal)} unit={t('dashArrivalsUnit')} />
                {peakHour ? (
                  <p className="chart-head-note">
                    {t('dashArrivalsPeak', { hour: peakHour.tick, n: peakHour.value })}
                  </p>
                ) : null}
              </div>
            <TrendArea
              points={arrivals}
              liveUntil={arrivalsLiveUntil}
              label={t('dashArrivalsAria', {
                list: arrivals
                  .filter((p) => p.value > 0)
                  .map((p) => `${p.tick}:00 ${p.value}`)
                  .join(', '),
              })}
              formatPoint={(p) => t('dashArrivalsPoint', { hour: p.tick, n: p.value })}
            />
            </>
          )}
        </Panel>
      </Band>

      <Band title={range ? t('dashRangeHeading', { n: days }) : t('dashLastDays', { n: days })}>
        <Panel
          title={t('dashAcuityTitle')}
          subtitle={t('dashAcuitySub')}
        >
          {acuityTotal === 0 ? (
            <EmptyNote text={t('dashNoScreenings')} />
          ) : (
            <ShareStrip rows={acuityShares} total={acuityTotal} />
          )}
        </Panel>

        <Panel title={t('dashDepartmentTitle')} subtitle={t('dashDepartmentSub')}>
          {departmentRows.length === 0 ? (
            <EmptyNote text={t('dashNoRouting')} />
          ) : (
            <DotPlot rows={departmentRows} axisLabel={t('dashDeptAxis')} />
          )}
        </Panel>

        <Panel title={t('dashAgreement')} subtitle={t('dashAgreementSub')}>
          {!agreement || agreement.reviewed === 0 ? (
            <EmptyNote text={t('dashNoReviewsYet')} />
          ) : (
            <>
              <Figure
                value={agreementPct === null ? '—' : `${agreementPct}`}
                unit="%"
                delta={{
                  text: t('dashAgreementValue', {
                    confirmed: agreement.confirmed,
                    reviewed: agreement.reviewed,
                  }),
                  up: null,
                }}
              />
              {rerouteTargets.length > 0 ? (
                <ul className="reroute-list">
                  {rerouteTargets.map(([name, count]) => (
                    <li key={name}>
                      <ArrowRight size={14} weight="bold" aria-hidden="true" />
                      <span className="reroute-name">{name}</span>
                      <span className="reroute-count">{nf.format(count)}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
              <p className="dash-footnote">
                {t('dashAvgReviewTime')} · {formatDuration(agreement.avg_review_minutes)}
              </p>
            </>
          )}
        </Panel>

      </Band>
    </div>
  );
}
