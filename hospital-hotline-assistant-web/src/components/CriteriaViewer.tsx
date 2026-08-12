import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

// ── Tolerant shapes for the criteria JSONB (server sends the raw document) ──

interface Cond {
  finding_id?: string;
  vital?: string;
  op?: string;
  value?: number;
  age_band?: string;
  all_of?: Cond[];
  any_of?: Cond[];
}

interface FindingDef {
  label_en?: string;
  label_th?: string;
  synonyms_en?: string[];
  synonyms_th?: string[];
}

interface RuleLike {
  id?: string;
  label_en?: string;
  label_th?: string;
  citation?: string;
  condition?: Cond;
  level?: number;
  min_level?: number;
  force_min_level?: number;
  findings_all?: string[];
  risk_factors_any?: string[];
  department_code?: string;
  complaint_category?: string;
}

interface QuestionOption {
  id?: string;
  text_en?: string;
  text_th?: string;
}

interface Question {
  id?: string;
  kind?: string;
  slot?: string;
  vital?: string;
  text_en?: string;
  text_th?: string;
  finding_ids?: string[];
  options?: QuestionOption[];
}

interface Template {
  category?: string;
  label_en?: string;
  label_th?: string;
  keywords_en?: string[];
  keywords_th?: string[];
  questions?: Question[];
}

interface SourceStandard {
  name?: string;
  edition?: string;
  url?: string;
}

type CriteriaDoc = Record<string, unknown>;

function asArr<T>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : [];
}

function asObj<T>(v: unknown): Record<string, T> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, T>) : {};
}

/** Pick the bilingual label for the current language, falling back to the other. */
function bl(item: { label_en?: string; label_th?: string } | undefined, lang: string): string {
  if (!item) return '—';
  return (lang === 'th' ? item.label_th || item.label_en : item.label_en || item.label_th) || '—';
}

// The schema's operator names are lt/le/gt/ge/eq — `le`/`ge` were missing here
// and rendered raw ("SBP le 90") in the draft viewer.
const OPS: Record<string, string> = { gt: '>', ge: '≥', gte: '≥', lt: '<', le: '≤', lte: '≤', eq: '=' };

/** Compact human-readable rendering of the condition AST (all_of/any_of/finding/vital). */
function condText(
  c: Cond | undefined,
  findings: Record<string, FindingDef>,
  lang: string,
  depth = 0,
): string {
  if (!c) return '—';
  const and = lang === 'th' ? ' และ ' : ' AND ';
  const or = lang === 'th' ? ' หรือ ' : ' OR ';
  let core = '';
  let composite = 0;
  if (c.finding_id) {
    core = bl(findings[c.finding_id], lang);
    if (core === '—') core = c.finding_id;
  } else if (c.vital) {
    core = `${c.vital.toUpperCase()} ${OPS[c.op ?? ''] ?? c.op ?? '?'} ${c.value ?? '?'}`;
  } else if (c.all_of?.length) {
    composite = c.all_of.length;
    core = c.all_of.map((x) => condText(x, findings, lang, depth + 1)).join(and);
  } else if (c.any_of?.length) {
    composite = c.any_of.length;
    core = c.any_of.map((x) => condText(x, findings, lang, depth + 1)).join(or);
  }
  if (depth > 0 && composite > 1) core = `(${core})`;
  if (c.age_band) core = `[${c.age_band}] ${core}`;
  return core || '—';
}

// ── Sources banner ───────────────────────────────────────────────────────────

export function CriteriaSources({ doc }: { doc: CriteriaDoc }) {
  const { t } = useTranslation();
  const sources = asArr<SourceStandard>(doc.source_standards).filter((s) => s.name);
  if (sources.length === 0) {
    return <p className="cm-sources muted">{t('criteriaSourceDefault')}</p>;
  }
  return (
    <p className="cm-sources">
      <span className="muted">{t('criteriaSourcesBasedOn')}</span>{' '}
      {sources.map((s, i) => {
        const label = s.edition ? `${s.name} (${s.edition})` : s.name;
        return s.url ? (
          <a
            key={`${s.name}-${i}`}
            className="cm-source-link"
            href={s.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {label} ↗
          </a>
        ) : (
          <span key={`${s.name}-${i}`} className="cm-source-link">
            {label}
          </span>
        );
      })}
    </p>
  );
}

// ── Pagination ───────────────────────────────────────────────────────────────

const PAGE_SIZE = 15;

function usePaged<T>(rows: T[]): { page: T[]; pager: React.ReactNode } {
  const [pageNo, setPageNo] = useState(0);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const clamped = Math.min(pageNo, pages - 1);
  const page = rows.slice(clamped * PAGE_SIZE, (clamped + 1) * PAGE_SIZE);
  const pager =
    pages > 1 ? (
      <div className="cm-pager">
        <button
          type="button"
          className="secondary-btn cm-pager-btn"
          disabled={clamped === 0}
          onClick={() => setPageNo(clamped - 1)}
          aria-label="previous page"
        >
          ‹
        </button>
        <span className="cm-pager-label">
          {clamped + 1}/{pages}
        </span>
        <button
          type="button"
          className="secondary-btn cm-pager-btn"
          disabled={clamped >= pages - 1}
          onClick={() => setPageNo(clamped + 1)}
          aria-label="next page"
        >
          ›
        </button>
      </div>
    ) : null;
  return { page, pager };
}

// ── Rules table (red-flags + routing sections) ───────────────────────────────

interface RuleRow {
  key: string;
  group: string;
  label: string;
  cond: string;
  effect: string;
  citation: string;
}

function RuleTable({ rows }: { rows: RuleRow[] }) {
  const { t } = useTranslation();
  const { page, pager } = usePaged(rows);
  if (rows.length === 0) return <p className="muted">{t('criteriaViewerEmpty')}</p>;
  return (
    <>
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
            {page.map((r) => (
              <tr key={r.key}>
                <td>
                  <span className="cm-pill cm-group-pill">{r.group}</span>
                  <div className="cm-rule-label">{r.label}</div>
                </td>
                <td className="cm-cond">{r.cond}</td>
                <td className="cm-effect">{r.effect}</td>
                <td className="cm-cite">{r.citation || t('criteriaCiteFallback')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pager}
    </>
  );
}

// ── Section: complaint templates ─────────────────────────────────────────────

function TemplatesSection({ doc, lang }: { doc: CriteriaDoc; lang: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const templates = asArr<Template>(doc.complaint_templates);
  const findings = asObj<FindingDef>(doc.finding_catalog);
  if (templates.length === 0) return <p className="muted">{t('criteriaViewerEmpty')}</p>;
  const otherLang = lang === 'th' ? 'en' : 'th';
  return (
    <div className="cm-tpl-list">
      {templates.map((tpl) => {
        const cat = tpl.category ?? '?';
        const isOpen = !!open[cat];
        const keywords = (lang === 'th' ? tpl.keywords_th : tpl.keywords_en) ?? [];
        const questions = tpl.questions ?? [];
        return (
          <div key={cat} className="cm-tpl-card">
            <button
              type="button"
              className="cm-tpl-head"
              aria-expanded={isOpen}
              onClick={() => setOpen((s) => ({ ...s, [cat]: !s[cat] }))}
            >
              <span className="cm-tpl-toggle" aria-hidden="true">
                {isOpen ? '▾' : '▸'}
              </span>
              <span className="cm-tpl-title">{bl(tpl, lang)}</span>
              <span className="muted cm-tpl-sub">{bl(tpl, otherLang)}</span>
              <code className="cm-tpl-cat">{cat}</code>
              <span className="muted cm-tpl-count">
                {t('criteriaQuestionsN', { n: questions.length })}
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
                <ul className="cm-q-list">
                  {questions.map((q) => {
                    const isRedFlag = q.kind === 'red_flag';
                    return (
                      <li key={q.id ?? q.text_en} className={`cm-q ${isRedFlag ? 'cm-q-redflag' : ''}`}>
                        <span className={`cm-kind-badge cm-kind-${q.kind ?? 'unknown'}`}>
                          {q.kind ?? '?'}
                        </span>
                        <div className="cm-q-text">
                          <div>{lang === 'th' ? q.text_th || q.text_en : q.text_en || q.text_th}</div>
                          <div className="muted cm-q-alt">
                            {lang === 'th' ? q.text_en : q.text_th}
                          </div>
                          {(q.finding_ids?.length ?? 0) > 0 && (
                            <div className="cm-q-findings muted">
                              {q.finding_ids?.map((f) => bl(findings[f], lang)).join(' · ')}
                            </div>
                          )}
                          {(q.options?.length ?? 0) > 0 && (
                            <div className="cm-q-chips">
                              {q.options?.map((o) => (
                                <span key={o.id ?? o.text_en} className="cm-pill">
                                  {lang === 'th' ? o.text_th || o.text_en : o.text_en || o.text_th}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Section: finding catalog ─────────────────────────────────────────────────

function FindingsSection({ doc, lang }: { doc: CriteriaDoc; lang: string }) {
  const { t } = useTranslation();
  const entries = Object.entries(asObj<FindingDef>(doc.finding_catalog));
  const { page, pager } = usePaged(entries);
  if (entries.length === 0) return <p className="muted">{t('criteriaViewerEmpty')}</p>;
  const otherLang = lang === 'th' ? 'en' : 'th';
  return (
    <>
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
            {page.map(([id, def]) => (
              <tr key={id}>
                <td>
                  <code>{id}</code>
                </td>
                <td>
                  <div>{bl(def, lang)}</div>
                  <div className="muted cm-q-alt">{bl(def, otherLang)}</div>
                </td>
                <td className="cm-q-chips">
                  {((lang === 'th' ? def.synonyms_th : def.synonyms_en) ?? []).map((s) => (
                    <span key={s} className="cm-pill">
                      {s}
                    </span>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pager}
    </>
  );
}

// ── Main viewer ──────────────────────────────────────────────────────────────

type SectionId = 'templates' | 'redflags' | 'routing' | 'findings';

export function CriteriaViewer({ doc }: { doc: CriteriaDoc }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language?.startsWith('th') ? 'th' : 'en';
  const [section, setSection] = useState<SectionId>('templates');

  const findings = useMemo(() => asObj<FindingDef>(doc.finding_catalog), [doc]);
  const levelWord = t('aiMetricsLevel');

  const redFlagRows = useMemo<RuleRow[]>(() => {
    const rows: RuleRow[] = [];
    for (const r of asArr<RuleLike>(doc.level1_criteria)) {
      rows.push({
        key: `l1-${r.id}`,
        group: t('criteriaGroupLevel1'),
        label: bl(r, lang),
        cond: condText(r.condition, findings, lang),
        effect: `${levelWord} 1`,
        citation: r.citation ?? '',
      });
    }
    for (const r of asArr<RuleLike>(doc.danger_vitals)) {
      rows.push({
        key: `dv-${r.id}`,
        group: t('criteriaGroupDangerVitals'),
        label: bl(r, lang),
        cond: condText(r.condition, findings, lang),
        effect: `${levelWord} ${r.level ?? 2}`,
        citation: r.citation ?? '',
      });
    }
    for (const r of asArr<RuleLike>(doc.triage_tuples)) {
      const and = lang === 'th' ? ' และ ' : ' AND ';
      let cond = (r.findings_all ?? []).map((f) => bl(findings[f], lang)).join(and) || '—';
      if ((r.risk_factors_any?.length ?? 0) > 0) {
        cond += ` (+ ${r.risk_factors_any?.join(', ')})`;
      }
      rows.push({
        key: `tt-${r.id}`,
        group: t('criteriaGroupTuples'),
        label: bl(r, lang),
        cond,
        effect: `≥ ${levelWord} ${r.force_min_level ?? '?'}`,
        citation: r.citation ?? '',
      });
    }
    for (const r of asArr<RuleLike>(doc.fast_tracks)) {
      rows.push({
        key: `ft-${r.id}`,
        group: t('criteriaGroupFastTracks'),
        label: bl(r, lang),
        cond: condText(r.condition, findings, lang),
        effect: `${levelWord} ${r.level ?? '?'} → ${r.department_code ?? '?'}`,
        citation: r.citation ?? '',
      });
    }
    return rows;
  }, [doc, findings, lang, t, levelWord]);

  const routingRows = useMemo<RuleRow[]>(() => {
    const rows: RuleRow[] = [];
    for (const r of asArr<RuleLike>(doc.routing_table)) {
      rows.push({
        key: `rt-${r.complaint_category}-${r.department_code}`,
        group: t('criteriaGroupRouting'),
        label: r.complaint_category ?? '—',
        cond: '—',
        effect: `→ ${r.department_code ?? '?'}`,
        citation: r.citation ?? '',
      });
    }
    for (const r of asArr<RuleLike>(doc.department_rules)) {
      rows.push({
        key: `dr-${r.id}`,
        group: t('criteriaGroupDeptRules'),
        label: bl(r, lang),
        cond: condText(r.condition, findings, lang),
        effect: `≥ ${levelWord} ${r.min_level ?? '?'} → ${r.department_code ?? '?'}`,
        citation: r.citation ?? '',
      });
    }
    return rows;
  }, [doc, findings, lang, t, levelWord]);

  const tabs: { id: SectionId; label: string }[] = [
    { id: 'templates', label: t('criteriaSecTemplates') },
    { id: 'redflags', label: t('criteriaSecRedFlags') },
    { id: 'routing', label: t('criteriaSecRouting') },
    { id: 'findings', label: t('criteriaSecFindings') },
  ];

  return (
    <div className="cm-viewer">
      <div className="cm-sec-tabs" role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={section === tab.id}
            className={`cm-sec-tab ${section === tab.id ? 'cm-sec-tab-active' : ''}`}
            onClick={() => setSection(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {section === 'templates' && <TemplatesSection doc={doc} lang={lang} />}
      {section === 'redflags' && <RuleTable key="redflags" rows={redFlagRows} />}
      {section === 'routing' && <RuleTable key="routing" rows={routingRows} />}
      {section === 'findings' && <FindingsSection doc={doc} lang={lang} />}
    </div>
  );
}
