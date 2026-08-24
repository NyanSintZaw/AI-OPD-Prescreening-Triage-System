/**
 * Read-only "what does the booth actually decide?" view of the ACTIVE criteria.
 *
 * Everything here comes pre-rendered from GET /admin/criteria/active — the
 * condition AST is flattened to text server-side, so this file only lays out
 * what the nurse reads. No editing, no writes; version governance (upload,
 * approve, activate) stays in CriteriaManager.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { WarningCircle } from '@phosphor-icons/react';
import { api, type CriteriaActiveView } from '../api';
import type {
  CriteriaViewFinding,
  CriteriaViewQuestion,
  CriteriaViewRule,
} from '../api/types';
import { CriteriaSources } from './CriteriaViewer';

type Section = 'complaints' | 'rules' | 'findings' | 'routing';

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
  const [section, setSection] = useState<Section>('complaints');
  const [query, setQuery] = useState('');
  const [openCategory, setOpenCategory] = useState<string | null>(null);

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

  const placeholderCount = useMemo(() => {
    if (!view) return 0;
    return (
      view.rules.filter((r) => r.placeholder).length +
      view.routing.filter((r) => r.placeholder).length
    );
  }, [view]);

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

  const sections: Array<{ id: Section; label: string; count: number }> = [
    { id: 'complaints', label: t('criteriaSecTemplates'), count: view.complaint_templates.length },
    { id: 'rules', label: t('criteriaBookSecRules'), count: view.rules.length },
    { id: 'findings', label: t('criteriaSecFindings'), count: view.findings.length },
    { id: 'routing', label: t('criteriaGroupRouting'), count: view.routing.length },
  ];

  return (
    <section className="criteria-book">
      <div className="criteria-book-meta">
        <span className="cm-status-pill cm-status-active">
          {view.version_no != null ? `v${view.version_no}` : t('criteriaBookSeed')}
        </span>
        <span className="muted">
          {t('criteriaBookActiveSince')}: {formatDate(view.activated_at)}
        </span>
        {view.change_summary && <span className="cm-book-summary">{view.change_summary}</span>}
      </div>
      <CriteriaSources doc={view as unknown as Record<string, unknown>} />

      {placeholderCount > 0 && (
        <p className="alert-note alert-note-warning">
          <WarningCircle size={18} weight="duotone" aria-hidden="true" />
          {t('criteriaBookPlaceholderCount', { n: placeholderCount })}
        </p>
      )}

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
            {s.label} <span className="tab-count">{s.count}</span>
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

      {section === 'complaints' && (
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

          {view.complaint_templates.map((tpl) => {
            const isOpen = openCategory === tpl.category;
            const keywords = lang === 'th' ? tpl.keywords_th : tpl.keywords_en;
            return (
              <div key={tpl.category} className="cm-tpl-card">
                <button
                  type="button"
                  className="cm-tpl-head"
                  aria-expanded={isOpen}
                  onClick={() => setOpenCategory(isOpen ? null : tpl.category)}
                >
                  <span className="cm-tpl-toggle" aria-hidden="true">
                    {isOpen ? '▾' : '▸'}
                  </span>
                  <span className="cm-tpl-title">{label(tpl)}</span>
                  <code className="cm-tpl-cat">{tpl.category}</code>
                  <span className="muted cm-tpl-count">
                    {t('criteriaQuestionsN', { n: tpl.questions.length })}
                  </span>
                </button>
                {isOpen && (
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
                )}
              </div>
            );
          })}

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

      {section === 'rules' && (
        <div className="table-wrap">
          <table className="admin-table cm-rule-table">
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
        <div className="table-wrap">
          <table className="admin-table cm-rule-table">
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

      {section === 'routing' && (
        <div className="table-wrap">
          <table className="admin-table cm-rule-table">
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
    </section>
  );
}
