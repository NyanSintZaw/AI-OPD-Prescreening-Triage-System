/**
 * One session, opened from the admin log.
 *
 * Read-only by design: the admin portal inspects, the nurse portal decides.
 * It uses the nurse review dialog's shell so the two portals keep one overlay
 * vocabulary, and it is the first surface to render `/admin/sessions/{id}/trace`
 * — the engine's own record of the decision, built with migration 014 and
 * never mounted until now.
 *
 * It owns its own exit, like `InfoDialog`: its parent mounts it from a row, so
 * it cannot delay its own unmount — it flags itself leaving, lets the CSS run,
 * then calls `onClose`.
 */
import { useEffect, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from '@phosphor-icons/react';
import { useDialogExit } from '../../hooks/useDialogExit';
import { api } from '../../api';
import type { AdminSessionRow, MessageOut, SessionTraceOut } from '../../api/types';
import { MessageBubble } from '../MessageBubble';
import { TriageBadge } from '../staff/TriageBadge';
import { Ledger, LedgerRow } from '../staff/Ledger';

type DetailTab = 'trace' | 'transcript' | 'vitals';

const VITAL_ORDER = ['sbp', 'dbp', 'hr', 'rr', 'spo2', 'temp', 'weight', 'height'] as const;
const nf = new Intl.NumberFormat();

/* What the booth always takes: the cuff (sbp), the thermometer (temp) and the
   pulse the cuff reports (hr). RR has no instrument here and never will have
   one; SpO2 is taken only when a case calls for it. Counting either as core
   made a complete screening report itself short and printed a permanent
   "Never measured: RR, SpO2" caution under every single session. Kept in sync
   with the same list in admin_analytics.py. */
const CORE_VITALS = ['sbp', 'hr', 'temp'];

/** A trace section: a heading that reads as one, with its counts riding
 *  beside it rather than as a faint line underneath. */
function TraceBlock({
  title,
  tags,
  children,
}: {
  title: string;
  tags?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="trace-block">
      <header className="trace-block-head">
        <h4>{title}</h4>
        {tags ? <div className="trace-block-tags">{tags}</div> : null}
      </header>
      {children}
    </section>
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asList(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(asRecord) : [];
}

/** The disposition the rules engine reached, and the criteria that took it
 *  there. This is the answer to "why did it say that" — the reason the trace
 *  endpoint exists. */
function DispositionSummary({ state, language }: { state: Record<string, unknown>; language: string }) {
  const { t } = useTranslation();
  const disposition = asRecord(state.disposition);
  if (!disposition.level) return null;
  const reasons = asList(disposition.reasons);
  const hits = asList(disposition.rule_hits);

  return (
    <TraceBlock title={t('adminTraceDisposition')}>
      {/* No badge here. The dialog header carries the level beside the session
          id and keeps it on every tab; repeating it 40px below said the same
          thing twice and made the second one look like a different fact. What
          this row adds is the destination. */}
      <div className="trace-disposition">
        <code className="code-chip">{String(disposition.department_code ?? '—')}</code>
        {disposition.age_assumed ? (
          <span className="trace-caution">{t('adminTraceAgeAssumed')}</span>
        ) : null}
      </div>
      {reasons.length > 0 && (
        /* The answer to "why did it say that" — the reason this endpoint
           exists — used to be two unstyled sentences with the criteria
           citation shoved against the far edge, 900px from the clause it
           cites. Each reason is now a card carrying its own citation. */
        <ul className="trace-reasons">
          {reasons.map((reason, i) => (
            <li key={`${reason.rule_id}-${i}`}>
              <span className="trace-reason-text">
                {String((language === 'th' ? reason.text_th : reason.text_en) ?? reason.rule_id)}
              </span>
              {reason.citation ? (
                <span className="trace-citation">{String(reason.citation)}</span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {hits.length > 0 && (
        <p className="trace-rules">
          <span className="trace-label">{t('adminTraceFiredRules')}</span>
          {hits.map((hit, i) => (
            <code key={`${hit.rule_id}-${i}`} className="code-chip">
              {String(hit.rule_id)}
            </code>
          ))}
        </p>
      )}
    </TraceBlock>
  );
}

/** A criteria id as a person reads it: `severe_respiratory_distress` becomes
 *  "Severe respiratory distress". The ids come from the criteria file and have
 *  no translation table, so this is mechanical — the raw id stays on `title`
 *  for anyone matching a row against the criteria book. */
function humanise(id: string): string {
  const words = id.replace(/_/g, ' ').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * What the extractor believed, split into present and absent.
 *
 * These used to be one ragged wrap of chips: present and absent interleaved,
 * absent ones struck through — which reads as "deleted", not "asked and
 * answered no" — and every chip a different width because some carry a
 * sentence of value and most carry nothing. Nothing aligned, so the only way
 * to find a finding was to read all thirty.
 *
 * They are two different shapes and now get two forms. A present finding is a
 * label and a value, which is a ledger. An absent one is a bare name, and
 * there are many, so they are a quiet uniform wrap underneath.
 *
 * Absent findings are not filler: they are why a red flag did NOT fire, which
 * is the question a reviewer brings to this tab.
 */
function FindingsBlock({ state }: { state: Record<string, unknown> }) {
  const { t } = useTranslation();
  const findings = asRecord(state.findings);
  const entries = Object.entries(findings).map(([id, raw]) => ({ id, f: asRecord(raw) }));
  if (entries.length === 0) return null;

  const present = entries.filter((e) => e.f.state !== 'absent');
  const absent = entries.filter((e) => e.f.state === 'absent');

  return (
    <TraceBlock
      title={t('adminTraceFindings')}
      tags={
        <>
          {present.length > 0 && (
            <span className="status-chip chip-approved">
              {t('adminTracePresent', { n: present.length })}
            </span>
          )}
          {absent.length > 0 && (
            <span className="status-chip chip-active">
              {t('adminTraceAbsent', { n: absent.length })}
            </span>
          )}
        </>
      }
    >
      {/* Side by side, because they are the two halves of one answer — and
          stacked they left a third of a 78rem card empty beside each. */}
      <div className="trace-findings-split">
        {present.length > 0 && (
          <Ledger className="trace-findings">
            {present.map(({ id, f }) => (
              <LedgerRow
                key={id}
                label={humanise(id)}
                value={f.value ? String(f.value) : t('adminTraceConfirmed')}
              />
            ))}
          </Ledger>
        )}

        {absent.length > 0 && (
          /* Every chip leads with a minus. Without it these read as a second
             list of things the patient HAS — the group label alone is one word
             at the top of a wrap of twelve, and the eye never gets back to it.
             They are not filler: an absent finding is why a red flag did not
             fire, which is the question a reviewer brings to this tab. */
          <div className="trace-absent-group">
            <p className="trace-sublabel">{t('adminTraceAbsentLead')}</p>
            <ul className="trace-absent">
              {absent.map(({ id }) => (
                <li key={id} title={id}>
                  <span className="trace-absent-mark" aria-hidden="true">
                    −
                  </span>
                  {humanise(id)}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </TraceBlock>
  );
}

/**
 * Every model call this session made, grouped by turn.
 *
 * A turn is one exchange, and it is almost always the same pair: read what the
 * patient said, then decide what to ask next. Stacked vertically that pair
 * filled the panel — an eleven-turn session ran to twenty-two rows and the
 * turn structure, which is the thing worth seeing, was invisible.
 *
 * Each turn is now a row and its calls sit side by side, so the shape of the
 * conversation is legible at a glance and a turn that did something unusual —
 * three calls, or a disposition — is obvious by not matching its neighbours.
 */
function AuditTimeline({ trace }: { trace: SessionTraceOut }) {
  const { t } = useTranslation();
  if (trace.audit.length === 0) return <p className="muted">{t('adminTraceNoCalls')}</p>;

  const turns: Array<{ turn: number; calls: SessionTraceOut['audit'] }> = [];
  trace.audit.forEach((entry) => {
    const last = turns[turns.length - 1];
    if (last && last.turn === entry.turn_no) last.calls.push(entry);
    else turns.push({ turn: entry.turn_no, calls: [entry] });
  });

  const slowest = Math.max(...trace.audit.map((e) => e.latency_ms ?? 0));
  const failed = trace.audit.filter((e) => !e.ok).length;

  return (
    <TraceBlock
      title={t('adminTraceTimeline')}
      tags={
        <>
          <span className="status-chip chip-active">
            {t('adminTraceCalls', { n: trace.audit.length })}
          </span>
          {failed > 0 && (
            <span className="status-chip chip-abandoned">
              {t('adminTraceFailedCount', { n: failed })}
            </span>
          )}
        </>
      }
    >
      <ol className="trace-turns">
        {turns.map(({ turn, calls }) => (
          <li key={turn} className="trace-turn-row">
            <span className="trace-turn">{t('adminTraceTurn', { n: turn })}</span>
            <div className="trace-turn-calls">
              {calls.map((entry, i) => {
                const payload =
                  entry.rules_trace && Object.keys(entry.rules_trace).length > 0
                    ? entry.rules_trace
                    : null;
                return (
                  <div
                    key={i}
                    className={`trace-call ${entry.ok ? '' : 'is-failed'} ${
                      entry.latency_ms === slowest && slowest > 0 ? 'is-slowest' : ''
                    }`}
                  >
                    <div className="trace-call-head">
                      <span className="trace-site">
                        {t(`dashCallSite_${entry.call_site}`, { defaultValue: entry.call_site })}
                      </span>
                      <span className="trace-latency">
                        {entry.latency_ms !== null ? `${nf.format(entry.latency_ms)} ms` : ''}
                      </span>
                    </div>
                    {!entry.ok && (
                      <span className="status-chip chip-abandoned">{t('adminTraceFailed')}</span>
                    )}

                    {/* Collapsed by default: an eleven-turn session's extraction
                        payloads are thousands of lines, and they buried the
                        timeline this tab exists to show. A failed call opens
                        itself. */}
                    {payload ? (
                      <details className="trace-detail" open={!entry.ok}>
                        <summary>{t('adminTracePayload')}</summary>
                        <pre className="trace-json">{JSON.stringify(payload, null, 2)}</pre>
                      </details>
                    ) : null}
                    {entry.validator_result ? (
                      <details className="trace-detail" open>
                        <summary>{t('adminTraceViolation')}</summary>
                        <pre className="trace-json is-violation">
                          {JSON.stringify(entry.validator_result, null, 2)}
                        </pre>
                      </details>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </li>
        ))}
      </ol>
    </TraceBlock>
  );
}

/**
 * Measured vs reported, because they are not the same evidence. A cuff reading
 * and a number the patient said out loud carry very different weight, and a
 * vital nobody ever took is the undertriage caution — it must never render as
 * a reassuring blank.
 */
function VitalsTab({ row, state }: { row: AdminSessionRow; state: Record<string, unknown> }) {
  const { t } = useTranslation();
  const measured = asRecord(state.measured_vitals);
  const reported = asRecord(state.vitals);
  const rejected = asRecord(state.rejected_vitals);
  const keys = VITAL_ORDER.filter(
    (k) => k in measured || k in reported || k in rejected,
  );

  return (
    <>
      <TraceBlock title={t('adminVitalsTitle')}>
        {keys.length === 0 ? (
          <p className="muted">{t('adminVitalsNone')}</p>
        ) : (
          <ul className="trace-vitals">
            {keys.map((key) => {
              const bad = asRecord(rejected[key]);
              return (
                <li key={key}>
                  <span className="trace-vital-key">
                    {t(`nurseMissingVitalName_${key}`, { defaultValue: key })}
                  </span>
                  {bad.value !== undefined ? (
                    <span className="trace-vital-rejected">
                      <s>{String(bad.value)}</s> {t('adminVitalsRejected')}
                    </span>
                  ) : (
                    <span className="trace-vital-value">
                      {String(measured[key] ?? reported[key] ?? '—')}
                    </span>
                  )}
                  {/* Its own column, so the chips line up down the list. It
                      used to trail the value, which put it at a different x on
                      every row and made three identical words read as three
                      different things. */}
                  <span className="trace-vital-source">
                    <span
                      className={`status-chip ${key in measured ? 'chip-device' : 'chip-patient'}`}
                    >
                      {key in measured ? t('adminVitalsMeasured') : t('adminVitalsReported')}
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
        )}
        {row.outcome === 'disposed' && (
          <p className="trace-vitals-coverage">
            {t('adminVitalsCoverage', { n: row.vitals_measured, of: row.vitals_core })}
            {CORE_VITALS.filter((k) => !(k in measured)).length > 0 ? (
              <span className="trace-caution">
                {t('adminVitalsMissing', {
                  list: CORE_VITALS.filter((k) => !(k in measured))
                    .map((k) => t(`nurseMissingVitalName_${k}`, { defaultValue: k }))
                    .join(', '),
                })}
              </span>
            ) : null}
          </p>
        )}
      </TraceBlock>

      <TraceBlock title={t('adminHisTitle')}>
        <ul className="trace-kv">
          <li>
            <span>{t('adminHisPush')}</span>
            <span className={row.his_status === 'failed' ? 'is-danger' : ''}>
              {row.his_status
                ? t(`adminMetaHis_${row.his_status}`, { defaultValue: row.his_status })
                : t('adminHisNotLinked')}
            </span>
          </li>
          <li>
            <span>{t('adminColPatient')}</span>
            <span>{row.patient_hn ? `HN ${row.patient_hn}` : t('adminWalkIn')}</span>
          </li>
        </ul>
      </TraceBlock>
    </>
  );
}

export function SessionDetailDialog({
  row,
  onClose,
}: {
  row: AdminSessionRow;
  onClose: () => void;
}) {
  const { t, i18n } = useTranslation();
  const [tab, setTab] = useState<DetailTab>('trace');
  const [trace, setTrace] = useState<SessionTraceOut | null>(null);
  const [traceError, setTraceError] = useState<string | null>(null);
  const [messages, setMessages] = useState<MessageOut[] | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const { leaving, close } = useDialogExit(onClose);

  // Escape closes — a modal without it traps keyboard users.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [close]);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setTrace(null);
    setTraceError(null);
    void api
      .getSessionTrace(row.session_id)
      .then((data) => {
        if (!cancelled) setTrace(data);
      })
      .catch((err: unknown) => {
        // A session that predates the screening engine has no trace. That is a
        // fact about the session, not an error the admin must act on.
        if (!cancelled) setTraceError(err instanceof Error ? err.message : t('error'));
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [row.session_id, t]);

  // Loaded when the dialog opens, not when the tab is first visited.
  //
  // Deferring it was meant to save the fattest payload on sessions opened only
  // for the trace — but the tab carries a message count, so deferring left a
  // "…" sitting on the tab for as long as the dialog was open, which reads as
  // stuck rather than as lazy. The count cannot come from the row's `turns`
  // either: that is user messages only, so a 23-message transcript says 11.
  //
  // The saving was never real at this scale — a transcript is a few kB and the
  // trace request already goes out on open — and it cost the reader a wait
  // every time they did switch tabs.
  useEffect(() => {
    let cancelled = false;
    void api
      .listMessages(row.session_id)
      .then((data) => {
        if (!cancelled) setMessages(data);
      })
      .catch(() => {
        if (!cancelled) setMessages([]);
      });
    return () => {
      cancelled = true;
    };
  }, [row.session_id]);

  const state = asRecord(trace?.engine_state);

  return (
    <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="admin-session-title">
      <button
        type="button"
        className="dialog-backdrop"
        data-leaving={leaving || undefined}
        aria-label={t('close')}
        onClick={close}
      />
      <div className="dialog-card" data-leaving={leaving || undefined}>
        <header className="dialog-head">
          <div className="dialog-identity">
            <TriageBadge level={row.triage_level} size="lg" />
            <div>
              {/* The session id leads, in full. On this surface the session IS
                  the subject — an administrator arrives from a log row, a
                  trace, or a support ticket, and matches on the id. The HN
                  identifies a patient, which is the nurse's question, not
                  this one; it drops to the meta line beside the timestamp.
                  Truncated to eight characters it could not be matched
                  against anything, which is the only job it had. */}
              <h2 id="admin-session-title" className="dialog-identity-id">
                {row.session_id}
              </h2>
              <p className="dialog-identity-meta">
                <span className="status-chip chip-patient">
                  {row.patient_hn ? `HN ${row.patient_hn}` : t('adminWalkIn')}
                </span>
                <span>{new Date(row.started_at).toLocaleString()}</span>
                {trace?.prompt_version ? (
                  <span>{t('adminPromptVersion', { v: trace.prompt_version })}</span>
                ) : null}
                {row.criteria_version !== null ? (
                  <span>{t('adminMetaCriteria', { n: row.criteria_version })}</span>
                ) : null}
              </p>
            </div>
          </div>
          <button type="button" className="icon-btn" onClick={close} aria-label={t('close')}>
            <X size={20} aria-hidden="true" />
          </button>
        </header>

        <div className="tabs" role="tablist">
          {(['trace', 'transcript', 'vitals'] as const).map((id) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              className={`tab ${tab === id ? 'active' : ''}`}
              onClick={() => setTab(id)}
            >
              {t(`adminTab_${id}`)}
              {id === 'transcript' ? (
                <span className="tab-count">{messages === null ? '…' : messages.length}</span>
              ) : null}
            </button>
          ))}
        </div>

        {/* Keyed on the tab so the body remounts and its fade runs. */}
        <div className="dialog-body" key={tab}>
          {isLoading ? (
            <p className="muted">{t('loading')}</p>
          ) : tab === 'transcript' ? (
            messages === null ? (
              <p className="muted">{t('loading')}</p>
            ) : messages.length === 0 ? (
              <p className="muted">{t('adminNoMessages')}</p>
            ) : (
              /* `.transcript`, the same grid the nurse's conversation tab
                 uses. Both tabs already rendered `MessageBubble`, but this one
                 wrapped it in a plain flex column — and the bubble is written
                 as `display: contents` for that grid, so outside it the
                 speaker name fell above each message instead of into an
                 aligned gutter. Same component, two different results. */
              <div className="transcript">
                {messages.map((message) => (
                  <MessageBubble key={message.id} message={message} />
                ))}
              </div>
            )
          ) : traceError ? (
            <p className="muted">{t('adminTraceUnavailable')}</p>
          ) : tab === 'trace' ? (
            <>
              <DispositionSummary state={state} language={i18n.language} />
              <FindingsBlock state={state} />
              {trace ? <AuditTimeline trace={trace} /> : null}
            </>
          ) : (
            <VitalsTab row={row} state={state} />
          )}
        </div>
      </div>
    </div>
  );
}
