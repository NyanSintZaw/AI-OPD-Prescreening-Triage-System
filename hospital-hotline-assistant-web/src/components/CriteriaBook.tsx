/**
 * Read-only "what does the booth actually decide?" view of the ACTIVE criteria.
 *
 * Everything here comes pre-rendered from GET /admin/criteria/active — the
 * condition AST is flattened to text server-side, so this file only lays out
 * what the nurse reads. No editing, no writes; version governance (upload,
 * approve, activate) stays in CriteriaManager.
 */
import { memo, useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CaretRight, WarningCircle } from '@phosphor-icons/react';
import { api, type CriteriaActiveView } from '../api';
import type {
  CriteriaViewFinding,
  CriteriaViewQuestion,
  CriteriaViewRule,
} from '../api/types';

/** `always` is the fixed spine of every interview — the questions the booth
 *  asks whatever the complaint. `complaints` is the per-complaint set, which
 *  is a dropdown per category and reads as a different kind of thing. */
type Section = 'always' | 'complaints' | 'rules' | 'findings' | 'routing' | 'sources';

/** Rule group → the label key the existing criteria viewer already ships. */
const GROUP_KEY: Record<CriteriaViewRule['group'], string> = {
  level1: 'criteriaGroupLevel1',
  danger_vital: 'criteriaGroupDangerVitals',
  triage_tuple: 'criteriaGroupTuples',
  fast_track: 'criteriaGroupFastTracks',
  department_rule: 'criteriaGroupDeptRules',
};

function formatDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : '—';
}

/** Case-insensitive "does any of these fields contain the query". */
function matches(query: string, ...fields: Array<string | undefined>): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return fields.some((f) => (f ?? '').toLowerCase().includes(q));
}

function PlaceholderBadge() {
  const { t } = useTranslation();
  return (
    <span className="cm-flag" title={t('criteriaBookPlaceholderHint')}>
      <WarningCircle size={13} weight="duotone" aria-hidden="true" /> {t('criteriaBookPlaceholder')}
    </span>
  );
}

interface SourceStandard {
  name?: string;
  edition?: string;
  url?: string;
}

/**
 * What the criteria are built on.
 *
 * These were three wrapping chips, one of which ran to 160 characters because
 * `edition` carries the ESI scope note as well as the edition — as a chip it
 * read as a run-on sentence with a border round it. Two columns and a link
 * per row say the same thing at a glance.
 */
/** What GET /admin/triage-manual/file serves — `settings.triage_manual_path`.
 *  Used as the label when a criteria entry carries no edition of its own: the
 *  seed names it now, but versions deployed before that leave it blank. */
const HELD_MANUAL_FILE = 'triage_manual.pdf';

function SourcesTable({ sources }: { sources: SourceStandard[] }) {
  const { t } = useTranslation();
  const [openError, setOpenError] = useState<string | null>(null);

  // The route is bearer-guarded, so it cannot be an href. Fetch, hand the tab
  // an object URL, and release it once the viewer has had time to load.
  const openManual = async () => {
    setOpenError(null);
    try {
      const url = URL.createObjectURL(await api.getTriageManualFile());
      window.open(url, '_blank', 'noopener');
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      setOpenError(err instanceof Error ? err.message : t('error'));
    }
  };

  if (sources.length === 0) return <p className="muted">{t('criteriaSourceDefault')}</p>;
  return (
    <table className="staff-table cm-source-table">
      <thead>
        <tr>
          <th scope="col">{t('criteriaSourceColName')}</th>
          <th scope="col">{t('criteriaSourceColEdition')}</th>
          <th scope="col" />
        </tr>
      </thead>
      <tbody>
        {sources.map((src, i) => {
          // A published standard carries its own URL. The MFU manual is not
          // published anywhere — the portal holds the PDF and built the RAG
          // index from it — so a source with no URL is the one we serve.
          const isLocal = !src.url;
          return (
            <tr key={`${src.name}-${i}`}>
              <th scope="row">{src.name}</th>
              <td>{src.edition || (isLocal ? HELD_MANUAL_FILE : '—')}</td>
              <td className="cm-source-open">
                {src.url ? (
                  <a href={src.url} target="_blank" rel="noopener noreferrer">
                    {t('criteriaSourceOpen')} ↗
                  </a>
                ) : isLocal ? (
                  <>
                    <button type="button" className="link-btn" onClick={() => void openManual()}>
                      {t('criteriaSourceOpen')} ↗
                    </button>
                    {openError && <span className="cm-source-error">{openError}</span>}
                  </>
                ) : (
                  '—'
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/**
 * One complaint category, memoised.
 *
 * All twenty-four bodies stay mounted so they can animate open, which means a
 * naive render puts 195 question rows through React on every toggle. Measured:
 * the CSS toggle plus a forced layout costs **0.4ms**, and the same toggle
 * through React cost **71ms** — four dropped frames, and the whole of the
 * "not smooth" in the open. The animation was never the expensive part.
 *
 * The memo only holds while `onToggle` is stable, hence the `useCallback` on
 * the other side, and while `title` is passed in already computed rather than
 * derived here from a changing closure.
 */
const ComplaintCard = memo(function ComplaintCard({
  tpl,
  title,
  lang,
  isOpen,
  onToggle,
}: {
  tpl: CriteriaActiveView['complaint_templates'][number];
  title: string;
  lang: 'th' | 'en';
  isOpen: boolean;
  onToggle: (category: string) => void;
}) {
  const { t } = useTranslation();
  const keywords = lang === 'th' ? tpl.keywords_th : tpl.keywords_en;
  return (
    <div className="cm-tpl-card">
      <button
        type="button"
        className="cm-tpl-head"
        aria-expanded={isOpen}
        onClick={() => onToggle(tpl.category)}
      >
        {/* One caret that turns, not two glyphs swapped: a character that is
            replaced cannot rotate. */}
        <CaretRight size={13} weight="bold" className="cm-tpl-toggle" aria-hidden="true" />
        <span className="cm-tpl-title">{title}</span>
        <code className="cm-tpl-cat">{tpl.category}</code>
        <span className="muted cm-tpl-count">
          {t('criteriaQuestionsN', { n: tpl.questions.length })}
        </span>
      </button>
      {/* Always rendered, and collapsed by a `0fr → 1fr` grid row: height
          cannot be transitioned from `auto`, and unmounting the body means
          there is nothing on screen to animate — it simply blinks out. */}
      <div className="cm-collapse" data-open={isOpen || undefined}>
        <div className="cm-tpl-body">
          {keywords.length > 0 && (
            <p className="cm-tpl-keywords">
              <span className="muted">{t('criteriaKeywords')}:</span>{' '}
              {keywords.map((k) => (
                <span key={k} className="cm-pill">
                  {k}
                </span>
              ))}
            </p>
          )}
          <QuestionList questions={tpl.questions} lang={lang} />
        </div>
      </div>
    </div>
  );
});

function QuestionList({ questions, lang }: { questions: CriteriaViewQuestion[]; lang: 'th' | 'en' }) {
  const { t } = useTranslation();
  if (questions.length === 0) return <p className="muted">{t('criteriaViewerEmpty')}</p>;
  return (
    <ol className="cm-q-list cm-book-q-list">
      {questions.map((q, i) => (
        <li key={q.id ?? i} className={`cm-q ${q.kind === 'red_flag' ? 'cm-q-redflag' : ''}`}>
          <span className="cm-book-q-no">{i + 1}</span>
          <span className={`cm-kind-badge cm-kind-${q.kind ?? 'unknown'}`}>{q.kind ?? '?'}</span>
          <div className="cm-q-text">
            <div>{(lang === 'th' ? q.text_th : q.text_en) || q.text_en || q.text_th}</div>
            <div className="muted cm-q-alt">{lang === 'th' ? q.text_en : q.text_th}</div>
            <div className="muted cm-q-alt">
              {q.vital && (
                <span className="cm-pill">
                  {t('criteriaBookMeasures')}: {q.vital}
                  {q.min_age_years != null ? ` (${t('criteriaBookAgeAtLeast', { n: q.min_age_years })})` : ''}
                  {q.skip_for_gender ? ` (${t('criteriaBookGenderSkip', { g: q.skip_for_gender })})` : ''}
                </span>
              )}
              {q.finding_ids.map((f) => (
                <code key={f} className="cm-pill">
                  {f}
                </code>
              ))}
            </div>
            {q.options.length > 0 && (
              <div className="cm-q-chips">
                {q.options.map((o, oi) => (
                  <span key={o.id ?? oi} className="cm-pill">
                    {(lang === 'th' ? o.text_th : o.text_en) || o.text_en}
                  </span>
                ))}
              </div>
            )}
            {q.citation && <div className="cm-cite">{q.citation}</div>}
          </div>
        </li>
      ))}
    </ol>
  );
}

/** "OPD หู คอ จมูก (opd_ent)" instead of a bare code — same names the booth
 * speaks to patients. Falls back to the raw code for anything unmapped. */
function deptLabel(code?: string | null, nameTh?: string | null): string {
  if (!code) return '';
  return nameTh ? `${nameTh} (${code})` : code;
}

export function CriteriaBook() {
  const { t, i18n } = useTranslation();
  const lang: 'th' | 'en' = i18n.language?.startsWith('th') ? 'th' : 'en';

  const [view, setView] = useState<CriteriaActiveView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [section, setSection] = useState<Section>('always');
  const [query, setQuery] = useState('');
  const [openCategory, setOpenCategory] = useState<string | null>(null);
  /** Stable, so `ComplaintCard`'s memo actually holds — a fresh closure here
   *  would re-render all twenty-four cards on every toggle, which is exactly
   *  what this is here to stop. */
  const toggleCategory = useCallback(
    (category: string) => setOpenCategory((open) => (open === category ? null : category)),
    [],
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await api.getActiveCriteria();
        if (!cancelled) setView(data);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : t('error'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [t]);

  const label = (item: { label_en: string; label_th: string }) =>
    (lang === 'th' ? item.label_th : item.label_en) || item.label_en || item.label_th || '—';
  const condition = (item: { condition_en: string; condition_th: string }) =>
    (lang === 'th' ? item.condition_th : item.condition_en) || '—';

  const findings = useMemo<CriteriaViewFinding[]>(
    () =>
      (view?.findings ?? []).filter((f) =>
        matches(query, f.id, f.label_en, f.label_th, f.synonyms_en.join(' '), f.synonyms_th.join(' ')),
      ),
    [view, query],
  );

  const rules = useMemo<CriteriaViewRule[]>(
    () =>
      (view?.rules ?? []).filter((r) =>
        matches(
          query,
          r.id ?? '',
          r.label_en,
          r.label_th,
          r.condition_en,
          r.condition_th,
          r.citation,
          r.department_code ?? '',
        ),
      ),
    [view, query],
  );

  if (loading) return <p className="muted">{t('loading')}</p>;
  if (error || !view)
    return (
      <p className="alert-note alert-note-danger" role="alert">
        <WarningCircle size={18} weight="duotone" aria-hidden="true" />
        {error ?? t('error')}
      </p>
    );

  const levelWord = t('aiMetricsLevel');
  const effectOf = (r: CriteriaViewRule) => {
    const level = r.level != null ? `${levelWord} ${r.level}` : null;
    const min = r.min_level != null ? `≥ ${levelWord} ${r.min_level}` : null;
    return [level ?? min, r.department_code ? `→ ${deptLabel(r.department_code, r.department_name_th)}` : null]
      .filter(Boolean)
      .join(' ');
  };

  const sections: Array<{ id: Section; label: string; count?: number }> = [
    {
      id: 'always',
      label: t('criteriaSecAlways'),
      count: view.universal_questions.length + view.pre_disposition_questions.length,
    },
    { id: 'complaints', label: t('criteriaSecTemplates'), count: view.complaint_templates.length },
    { id: 'rules', label: t('criteriaBookSecRules'), count: view.rules.length },
    { id: 'findings', label: t('criteriaSecFindings'), count: view.findings.length },
    { id: 'routing', label: t('criteriaGroupRouting'), count: view.routing.length },
    { id: 'sources', label: t('criteriaSecSources') },
  ];

  return (
    <section className="criteria-book">
      <div className="tabs" role="tablist">
        {sections.map((s) => (
          <button
            key={s.id}
            type="button"
            role="tab"
            aria-selected={section === s.id}
            className={`tab ${section === s.id ? 'active' : ''}`}
            onClick={() => setSection(s.id)}
          >
            {s.label}
            {s.count !== undefined && <span className="tab-count">{s.count}</span>}
          </button>
        ))}
      </div>

      {(section === 'findings' || section === 'rules') && (
        <input
          type="search"
          className="field-input cm-book-search"
          value={query}
          placeholder={section === 'findings' ? t('criteriaBookSearchFindings') : t('criteriaBookSearchRules')}
          onChange={(e) => setQuery(e.target.value)}
          aria-label={section === 'findings' ? t('criteriaBookSearchFindings') : t('criteriaBookSearchRules')}
        />
      )}

      {/* Keyed on the section so the panel is a new element on every switch,
          which is what lets its fade run. It carries the book's own flex
          rules rather than sitting between them as a plain box — the tables
          inside are bounded by `flex: 1` against a fill-height column, and a
          neutral wrapper would swallow that and let them grow again. */}
      <div className="criteria-panel" key={section}>
        {section === 'always' && (
          <div className="cm-tpl-list">
            {view.universal_questions.length > 0 && (
              <div className="cm-tpl-card">
                <div className="cm-tpl-head">
                  <span className="cm-tpl-title">{t('criteriaBookUniversal')}</span>
                  <span className="muted cm-tpl-count">
                    {t('criteriaQuestionsN', { n: view.universal_questions.length })}
                  </span>
                </div>
                <div className="cm-tpl-body">
                  <QuestionList questions={view.universal_questions} lang={lang} />
                </div>
              </div>
            )}

            {view.pre_disposition_questions.length > 0 && (
              <div className="cm-tpl-card">
                <div className="cm-tpl-head">
                  <span className="cm-tpl-title">{t('criteriaBookClosing')}</span>
                  <span className="muted cm-tpl-count">
                    {t('criteriaQuestionsN', { n: view.pre_disposition_questions.length })}
                  </span>
                </div>
                <div className="cm-tpl-body">
                  <QuestionList questions={view.pre_disposition_questions} lang={lang} />
                </div>
              </div>
            )}
          </div>
        )}

        {section === 'complaints' && (
          <div className="cm-tpl-list">
            {view.complaint_templates.map((tpl) => (
              <ComplaintCard
                key={tpl.category}
                tpl={tpl}
                title={label(tpl)}
                lang={lang}
                isOpen={openCategory === tpl.category}
                onToggle={toggleCategory}
              />
            ))}
          </div>
        )}

        {section === 'rules' && (
          <div className="table-wrap scroll-slim">
            <table className="admin-table cm-rule-table cm-table-rules">
              <thead>
                <tr>
                  <th>{t('criteriaColRule')}</th>
                  <th>{t('criteriaColCondition')}</th>
                  <th>{t('criteriaColEffect')}</th>
                  <th>{t('criteriaColCitation')}</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={`${r.group}-${r.id}`}>
                    <td>
                      <span className="cm-pill cm-group-pill">{t(GROUP_KEY[r.group] ?? r.group)}</span>
                      <div className="cm-rule-label">{label(r)}</div>
                      <code className="cm-tpl-cat">{r.id}</code>
                    </td>
                    <td className="cm-cond">{condition(r)}</td>
                    <td className="cm-effect">{effectOf(r)}</td>
                    <td className="cm-cite">
                      {r.citation || t('criteriaCiteFallback')}
                      {r.placeholder && (
                        <>
                          <br />
                          <PlaceholderBadge />
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rules.length === 0 && <p className="muted">{t('criteriaViewerEmpty')}</p>}
          </div>
        )}

        {section === 'findings' && (
          <div className="table-wrap scroll-slim">
            <table className="admin-table cm-rule-table cm-table-findings">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>{t('criteriaFindingLabel')}</th>
                  <th>{t('criteriaSynonyms')}</th>
                </tr>
              </thead>
              <tbody>
                {findings.map((f) => (
                  <tr key={f.id}>
                    <td>
                      <code>{f.id}</code>
                      {f.is_risk_factor && (
                        <div className="cm-pill cm-group-pill">{t('criteriaBookRiskFactor')}</div>
                      )}
                    </td>
                    <td>
                      <div>{label(f)}</div>
                      <div className="muted cm-q-alt">{lang === 'th' ? f.label_en : f.label_th}</div>
                    </td>
                    <td className="cm-q-chips">
                      {[...f.synonyms_th, ...f.synonyms_en].map((s) => (
                        <span key={s} className="cm-pill">
                          {s}
                        </span>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {findings.length === 0 && <p className="muted">{t('criteriaViewerEmpty')}</p>}
          </div>
        )}

        {section === 'sources' && (
          <div className="cm-sources-panel">
            <dl className="fact-grid">
              <div>
                <dt>{t('criteriaVersionLabel')}</dt>
                <dd>{view.version_no != null ? `v${view.version_no}` : t('criteriaBookSeed')}</dd>
              </div>
              <div>
                <dt>{t('criteriaBookActiveSince')}</dt>
                <dd>{formatDate(view.activated_at)}</dd>
              </div>
              {view.change_summary && (
                <div>
                  <dt>{t('criteriaVersionChange')}</dt>
                  <dd>{view.change_summary}</dd>
                </div>
              )}
            </dl>
            <div className="table-wrap scroll-slim">
              <SourcesTable
                sources={
                  (Array.isArray((view as { source_standards?: unknown }).source_standards)
                    ? ((view as { source_standards?: SourceStandard[] }).source_standards ?? [])
                    : []
                  ).filter((src) => src.name)
                }
              />
            </div>
          </div>
        )}

        {section === 'routing' && (
          <div className="table-wrap scroll-slim">
            <table className="admin-table cm-rule-table cm-table-routing">
              <thead>
                <tr>
                  <th>{t('criteriaColRule')}</th>
                  <th>{t('criteriaColCondition')}</th>
                  <th>{t('criteriaColEffect')}</th>
                  <th>{t('criteriaColCitation')}</th>
                </tr>
              </thead>
              <tbody>
                {view.routing.map((r) => (
                  <tr key={`${r.complaint_category}-${r.department_code}`}>
                    <td>
                      <code>{r.complaint_category}</code>
                    </td>
                    <td className="cm-cond">{condition(r) === '—' ? t('criteriaBookAlways') : condition(r)}</td>
                    <td className="cm-effect">
                      → {deptLabel(r.department_code, r.department_name_th)}
                      {r.fallback_department_code && (
                        <div className="muted">
                          {t('criteriaBookElse')} → {deptLabel(r.fallback_department_code, null)}
                        </div>
                      )}
                    </td>
                    <td className="cm-cite">
                      {r.citation || t('criteriaCiteFallback')}
                      {r.placeholder && (
                        <>
                          <br />
                          <PlaceholderBadge />
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
