/**
 * Admin ▸ Sessions — the booth's operations log.
 *
 * The nurse queue answers "is this patient routed right"; this answers "did
 * the booth work". So every column is something an admin can act on from the
 * left rail: a reroute points at the Rule Book, missing vitals at Device
 * Settings, a failed write-back at Database Settings, a criteria version at
 * the Rule Book again.
 *
 * Two deliberate absences:
 *  - No emergency/urgent/general. That was the patient-facing redaction of the
 *    engine's MOPH level, and it was never a staff fact.
 *  - No symptom text. An ops admin running a kiosk does not need to read what
 *    a patient said to know the kiosk is healthy; the transcript stays behind
 *    an explicit click, for audit.
 */
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowClockwise, CaretLeft, CaretRight } from '@phosphor-icons/react';
import { api } from '../../api';
import type {
  AdminSessionRow,
  AdminSessionsOut,
  SessionFlag,
  SessionOutcome,
  SessionWindow,
} from '../../api/types';
import { SelectField, type SelectOption } from '../ui/SelectField';
import { useLanguage } from '../../hooks/useSession';
import { TriageBadge } from '../staff/TriageBadge';
import { SessionDetailDialog } from './SessionDetailDialog';

const AUTO_REFRESH_INTERVAL_MS = 30_000;
const PAGE_SIZE = 50;
const SEARCH_DEBOUNCE_MS = 300;

const WINDOWS: SessionWindow[] = ['today', '7d', '30d', 'all'];
const LEVELS = [1, 2, 3, 4, 5] as const;
const OUTCOMES: SessionOutcome[] = ['disposed', 'abandoned', 'active'];
const LANGUAGES = ['th', 'en'] as const;

const nf = new Intl.NumberFormat();

/** The four exceptions the ribbon can show, in the order they matter. */
const FLAGS: Array<{ id: SessionFlag; countKey: keyof AdminSessionsOut['counts']; tone: string }> = [
  // Tones match the chips in the table below, so a colour means one thing on
  // this page: red is a patient the booth lost or a push that failed, gold is
  // a decision somebody still owes.
  { id: 'abandoned', countKey: 'abandoned', tone: 'danger' },
  { id: 'ai_error', countKey: 'ai_errors', tone: 'danger' },
  { id: 'his_failed', countKey: 'his_failed', tone: 'danger' },
  { id: 'unreviewed', countKey: 'unreviewed', tone: 'warning' },
];

function formatDuration(seconds: number | null): string {
  if (seconds === null || seconds <= 0) return '—';
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m === 0) return `${s}s`;
  if (m < 60) return `${m}m ${String(s).padStart(2, '0')}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`;
}

function relativeTime(value: string, t: (k: string, o?: Record<string, unknown>) => string): string {
  const diffMin = Math.floor((Date.now() - new Date(value).getTime()) / 60_000);
  if (diffMin < 1) return t('justNow');
  if (diffMin < 60) return t('minutesAgoShort', { n: diffMin });
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return t('hoursAgoShort', { n: diffH });
  return t('daysAgoShort', { n: Math.floor(diffH / 24) });
}

function shortDateTime(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * One quiet line of what is wrong, and nothing about what is fine — the
 * Dashboard tab already owns the healthy numbers. Every count is a filter, so
 * the ribbon is a way into the rows rather than a readout above them. Counts
 * are window-scoped, never filter-scoped: clicking one must not zero the rest.
 */
function Ribbon({
  data,
  flag,
  onToggleFlag,
}: {
  data: AdminSessionsOut | null;
  flag: SessionFlag | null;
  onToggleFlag: (next: SessionFlag | null) => void;
}) {
  const { t } = useTranslation();
  const counts = data?.counts;
  const shown = FLAGS.filter((f) => (counts?.[f.countKey] ?? 0) > 0);

  return (
    <div className="sess-ribbon">
      <span className="sess-ribbon-total">
        <strong>{nf.format(counts?.sessions ?? 0)}</strong> {t('adminRibbonSessions')}
      </span>
      {shown.length === 0 ? (
        <span className="sess-ribbon-clear">{t('adminRibbonClear')}</span>
      ) : (
        shown.map((f, i) => (
          /* The separator is its own element, not a `::before` on the button.
             As a pseudo-element it lived inside the button's padding, so a
             hover fill swallowed the dot and every flag looked wider on its
             left than its right. */
          <Fragment key={f.id}>
            {i > 0 || counts ? (
              <span className="sess-ribbon-sep" aria-hidden="true">
                ·
              </span>
            ) : null}
            <button
              type="button"
              className={`sess-ribbon-flag tone-${f.tone} ${flag === f.id ? 'active' : ''}`}
              aria-pressed={flag === f.id}
              onClick={() => onToggleFlag(flag === f.id ? null : f.id)}
            >
              <strong>{nf.format(counts?.[f.countKey] ?? 0)}</strong>
              {t(`adminRibbon_${f.id}`)}
            </button>
          </Fragment>
        ))
      )}
    </div>
  );
}

/** Outcome first, acuity inside it — an abandoned session has no level, and a
 *  dash in a LEVEL column reads as "not sick" rather than "never finished". */
function OutcomeCell({ row }: { row: AdminSessionRow }) {
  const { t } = useTranslation();
  if (row.outcome === 'disposed') {
    return (
      <span className="sess-outcome">
        <TriageBadge level={row.triage_level} />
        <span className="sess-level-name">{t(`triageLevelName_${row.triage_level}`)}</span>
      </span>
    );
  }
  return (
    <span className={`status-chip chip-${row.outcome}`}>{t(`adminOutcome_${row.outcome}`)}</span>
  );
}

/** Where the engine sent them, and where the nurse sent them instead. */
function RoutingCell({ row, language }: { row: AdminSessionRow; language: string }) {
  const pick = (en: string | null, th: string | null) =>
    (language === 'th' ? th ?? en : en) ?? null;
  const proposed = pick(row.proposed_department_en, row.proposed_department_th);
  const confirmed = pick(row.confirmed_department_en, row.confirmed_department_th);
  if (!proposed) return <span className="sess-dash">—</span>;
  const rerouted = confirmed && confirmed !== proposed;
  return (
    <span className="sess-routing">
      <span className={rerouted ? 'sess-routing-from' : ''}>{proposed}</span>
      {rerouted ? (
        <>
          <span className="sess-routing-arrow" aria-hidden="true">
            ▸
          </span>
          <span className="sess-routing-to">{confirmed}</span>
        </>
      ) : null}
    </span>
  );
}

/**
 * The quiet second tier: how the session actually ran. Anything that went
 * wrong tints itself here rather than earning a column of its own, so a
 * healthy row reads as one uninterrupted grey line and a sick one does not.
 */
function MetaLine({ row }: { row: AdminSessionRow }) {
  const { t } = useTranslation();
  const parts: Array<{ key: string; text: string; tone?: 'warning' | 'danger' }> = [
    { key: 'started', text: shortDateTime(row.started_at) },
    { key: 'turns', text: t('adminMetaTurns', { n: row.turns }) },
    { key: 'duration', text: formatDuration(row.duration_seconds) },
  ];

  if (row.avg_latency_ms !== null) {
    parts.push({ key: 'latency', text: t('adminMetaLatency', { n: row.avg_latency_ms }) });
  }
  // Vitals coverage is the undertriage signal AND the device-usage signal:
  // a booth whose cuff has gone unused shows it here before anyone checks
  // Device Settings.
  parts.push({
    key: 'vitals',
    text: t('adminMetaVitals', { n: row.vitals_measured, of: row.vitals_core }),
    tone: row.outcome === 'disposed' && row.vitals_measured === 0 ? 'warning' : undefined,
  });
  if (row.criteria_version !== null) {
    parts.push({ key: 'criteria', text: t('adminMetaCriteria', { n: row.criteria_version }) });
  }
  if (row.his_status) {
    parts.push({
      key: 'his',
      text: t(`adminMetaHis_${row.his_status}`, { defaultValue: `HIS ${row.his_status}` }),
      tone: row.his_status === 'failed' ? 'danger' : undefined,
    });
  }
  if (row.ai_error) {
    parts.push({ key: 'ai', text: t('adminMetaAiError'), tone: 'danger' });
  }
  parts.push({ key: 'lang', text: row.language.toUpperCase() });

  return (
    <span className="sess-meta">
      {parts.map((part, i) => (
        <span key={part.key} className={part.tone ? `sess-meta-item is-${part.tone}` : 'sess-meta-item'}>
          {i > 0 ? (
            <span className="sess-meta-sep" aria-hidden="true">
              ·
            </span>
          ) : null}
          {part.text}
        </span>
      ))}
    </span>
  );
}

export function SessionsPanel() {
  const { t } = useTranslation();
  const { language } = useLanguage();

  const [window_, setWindow] = useState<SessionWindow>('7d');
  const [level, setLevel] = useState<number | 'none' | null>(null);
  const [outcome, setOutcome] = useState<SessionOutcome | null>(null);
  const [lang, setLang] = useState<'th' | 'en' | null>(null);
  const [flag, setFlag] = useState<SessionFlag | null>(null);
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [offset, setOffset] = useState(0);

  const [data, setData] = useState<AdminSessionsOut | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
  const [selected, setSelected] = useState<AdminSessionRow | null>(null);

  useEffect(() => {
    const id = globalThis.setTimeout(() => setDebouncedSearch(search.trim()), SEARCH_DEBOUNCE_MS);
    return () => globalThis.clearTimeout(id);
  }, [search]);

  // Any change to what is being asked for starts at page one — paging into
  // row 200 of the old filter and then narrowing it lands on an empty page.
  useEffect(() => {
    setOffset(0);
  }, [window_, level, outcome, lang, flag, debouncedSearch]);

  const load = useCallback(
    async (options: { initial?: boolean } = {}) => {
      if (options.initial) setIsLoading(true);
      else setIsRefreshing(true);
      setError(null);
      try {
        const next = await api.listAdminSessions({
          window: window_,
          level: level ?? undefined,
          outcome: outcome ?? undefined,
          language: lang ?? undefined,
          flag: flag ?? undefined,
          q: debouncedSearch || undefined,
          limit: PAGE_SIZE,
          offset,
        });
        setData(next);
        setLastRefreshed(new Date());
      } catch (err) {
        setError(err instanceof Error ? err.message : t('error'));
      } finally {
        setIsLoading(false);
        setIsRefreshing(false);
      }
    },
    [window_, level, outcome, lang, flag, debouncedSearch, offset, t],
  );

  useEffect(() => {
    void load({ initial: data === null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load]);

  const autoRefreshRef = useRef(autoRefresh);
  autoRefreshRef.current = autoRefresh;
  const loadRef = useRef(load);
  loadRef.current = load;
  useEffect(() => {
    if (!autoRefresh) return;
    const id = globalThis.setInterval(() => {
      if (!autoRefreshRef.current) return;
      if (document.visibilityState !== 'visible') return;
      void loadRef.current();
    }, AUTO_REFRESH_INTERVAL_MS);
    return () => globalThis.clearInterval(id);
  }, [autoRefresh]);

  /* The same badge the rows carry, exactly as the nurse queue's level filter
     does it: the digit lives in the badge, so the label is only the name. The
     filter then shows the object it filters for rather than a second encoding
     of it — and DESIGN.md scopes triage colour to these surfaces precisely
     because this is the one meaning it carries. */
  const levelOptions: SelectOption[] = useMemo(
    () => [
      { value: 'all', label: t('adminLevelAll') },
      ...LEVELS.map((n) => ({
        value: String(n),
        label: t(`triageLevelName_${n}`),
        icon: <TriageBadge level={n} />,
      })),
      { value: 'none', label: t('adminLevelNone') },
    ],
    [t],
  );

  const outcomeOptions: SelectOption[] = useMemo(
    () => [
      { value: 'all', label: t('adminOutcomeAll') },
      ...OUTCOMES.map((id) => ({ value: id, label: t(`adminOutcome_${id}`) })),
    ],
    [t],
  );

  const languageOptions: SelectOption[] = useMemo(
    () => [
      { value: 'all', label: t('adminLanguageAll') },
      ...LANGUAGES.map((id) => ({ value: id, label: id.toUpperCase() })),
    ],
    [t],
  );

  const filtersActive =
    level !== null || outcome !== null || lang !== null || flag !== null || debouncedSearch !== '';

  const resetFilters = () => {
    setLevel(null);
    setOutcome(null);
    setLang(null);
    setFlag(null);
    setSearch('');
  };

  const rows = data?.rows ?? [];
  const total = data?.total ?? 0;
  const rangeLabel = useMemo(() => {
    if (total === 0) return null;
    return t('adminPagerRange', {
      from: nf.format(offset + 1),
      to: nf.format(Math.min(offset + rows.length, total)),
      total: nf.format(total),
    });
  }, [offset, rows.length, total, t]);

  return (
    <div className="sessions-panel">
      <div className="sess-ribbon-row">
        <Ribbon data={data} flag={flag} onToggleFlag={setFlag} />
        <div className="sess-ribbon-actions">
          <label className="staff-toggle">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            <span>{t('adminAutoRefresh')}</span>
          </label>
          <button
            type="button"
            className="icon-btn"
            onClick={() => void load()}
            disabled={isRefreshing || isLoading}
            aria-label={t('adminRefresh')}
            title={
              lastRefreshed
                ? `${t('adminLastRefreshed')}: ${lastRefreshed.toLocaleTimeString()}`
                : t('adminRefresh')
            }
          >
            <ArrowClockwise
              size={18}
              aria-hidden="true"
              className={isRefreshing ? 'is-spinning' : undefined}
            />
          </button>
        </div>
      </div>

      {/* The nurse queue's toolbar, verbatim: search first and full height,
          one segmented track for the period, and a dropdown for every filter
          whose options are a list rather than a choice you want in view. Five
          loose chip groups wrapped onto two rows and read as assembled. */}
      <div className="staff-toolbar sess-toolbar">
        <input
          type="search"
          className="field-input staff-search"
          placeholder={t('adminSearchPlaceholder')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label={t('adminSearchPlaceholder')}
        />

        <div className="chip-group" role="group" aria-label={t('adminWindowLabel')}>
          {WINDOWS.map((id) => (
            <button
              key={id}
              type="button"
              className={`filter-chip ${window_ === id ? 'active' : ''}`}
              onClick={() => setWindow(id)}
            >
              {t(`adminWindow_${id}`)}
            </button>
          ))}
        </div>

        <SelectField
          className="staff-toolbar-select sess-toolbar-select"
          value={level === null ? 'all' : String(level)}
          onChange={(v) => setLevel(v === 'all' ? null : v === 'none' ? 'none' : Number(v))}
          options={levelOptions}
          aria-label={t('adminLevelLabel')}
          emptyText={t('nurseNoMatches')}
        />

        <SelectField
          className="staff-toolbar-select sess-toolbar-select"
          value={outcome ?? 'all'}
          onChange={(v) => setOutcome(v === 'all' ? null : (v as SessionOutcome))}
          options={outcomeOptions}
          aria-label={t('adminOutcomeLabel')}
          emptyText={t('nurseNoMatches')}
        />

        <SelectField
          className="staff-toolbar-select sess-toolbar-select"
          value={lang ?? 'all'}
          onChange={(v) => setLang(v === 'all' ? null : (v as 'th' | 'en'))}
          options={languageOptions}
          aria-label={t('language')}
          emptyText={t('nurseNoMatches')}
        />

        {filtersActive && (
          <button type="button" className="text-btn" onClick={resetFilters}>
            {t('adminFiltersReset')}
          </button>
        )}
      </div>

      {error && (
        <div className="admin-error">
          <p className="error-text">{error}</p>
          <button type="button" className="secondary-btn" onClick={() => void load()}>
            {t('retry')}
          </button>
        </div>
      )}

      <div className="table-wrap sess-table-wrap">
        {isLoading ? (
          <ul className="sess-skeleton" aria-hidden="true">
            {Array.from({ length: 8 }, (_, i) => (
              <li key={i} />
            ))}
          </ul>
        ) : rows.length === 0 ? (
          <p className="muted admin-empty">
            {filtersActive ? t('adminEmptyFiltered') : t('adminEmptyWindow')}
          </p>
        ) : (
          <table className="admin-table sess-table">
            <thead>
              <tr>
                <th scope="col">{t('adminColOutcome')}</th>
                <th scope="col">{t('adminColPatient')}</th>
                <th scope="col">{t('adminColRouting')}</th>
                <th scope="col">{t('adminColReview')}</th>
                <th scope="col" className="sess-col-time">
                  {t('started')}
                </th>
              </tr>
            </thead>
            {rows.map((row) => (
              // Two rows per session, grouped: the primary line keeps the
              // columns aligned for scanning, the meta line gets full width
              // because none of it wants a column of its own.
              <tbody
                key={row.session_id}
                className={`sess-group ${row.triage_level === 1 || row.triage_level === 2 ? 'is-acute' : ''}`}
                onClick={() => setSelected(row)}
              >
                <tr className="sess-row">
                  <td>
                    <OutcomeCell row={row} />
                  </td>
                  <td>
                    {/* The keyboard path into the dialog. The whole group is
                        clickable for the mouse, but a div with an onClick is
                        not reachable without one. */}
                    <button
                      type="button"
                      className="sess-open"
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelected(row);
                      }}
                    >
                      {row.patient_hn ? (
                        <>
                          <span className="sess-hn-label">HN</span>
                          <span className="sess-hn">{row.patient_hn}</span>
                        </>
                      ) : (
                        <span className="sess-walkin">{t('adminWalkIn')}</span>
                      )}
                    </button>
                  </td>
                  <td>
                    <RoutingCell row={row} language={language} />
                  </td>
                  <td>
                    {row.review_status ? (
                      <span className={`status-chip chip-${row.review_status}`}>
                        {t(`adminReview_${row.review_status}`)}
                      </span>
                    ) : (
                      <span className="sess-dash">—</span>
                    )}
                  </td>
                  <td className="sess-col-time">{relativeTime(row.started_at, t)}</td>
                </tr>
                <tr className="sess-row-meta">
                  <td colSpan={5}>
                    <MetaLine row={row} />
                  </td>
                </tr>
              </tbody>
            ))}
          </table>
        )}
      </div>

      {total > PAGE_SIZE && (
        <footer className="sess-pager">
          <span className="sess-pager-range">{rangeLabel}</span>
          <button
            type="button"
            className="icon-btn"
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            disabled={offset === 0}
            aria-label={t('adminPagerPrev')}
          >
            <CaretLeft size={16} aria-hidden="true" />
          </button>
          <button
            type="button"
            className="icon-btn"
            onClick={() => setOffset(offset + PAGE_SIZE)}
            disabled={offset + rows.length >= total}
            aria-label={t('adminPagerNext')}
          >
            <CaretRight size={16} aria-hidden="true" />
          </button>
        </footer>
      )}

      {selected && <SessionDetailDialog row={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
