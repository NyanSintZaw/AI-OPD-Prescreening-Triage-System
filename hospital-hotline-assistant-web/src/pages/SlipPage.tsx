import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import type { SessionOut } from '../api/types';
import { getStoredLanguage } from '../i18n';
import { getStoredPatientName } from '../hooks/useSession';
import { slipCode } from '../utils/slipCode';

type VitalsMeta = {
  systolic?: number | null;
  diastolic?: number | null;
  pulse_bpm?: number | null;
  temperature?: number | null;
  weight_kg?: number | null;
  height_cm?: number | null;
};

function formatVital(value: number | null | undefined, digits = 0): string {
  if (value == null || Number.isNaN(Number(value))) return '—';
  return Number(value).toFixed(digits);
}

function formatBmi(
  weightKg: number | null | undefined,
  heightCm: number | null | undefined,
): string {
  if (!weightKg || !heightCm) return '—';
  return (Number(weightKg) / (Number(heightCm) / 100) ** 2).toFixed(1);
}

export function SlipPage() {
  const { t } = useTranslation();
  const { sessionId = '' } = useParams<{ sessionId: string }>();
  const language = getStoredLanguage();
  const [session, setSession] = useState<SessionOut | null>(null);
  const [departmentName, setDepartmentName] = useState<string | null>(null);
  const [navLine, setNavLine] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!sessionId) {
      setError(t('slipLoadError'));
      setLoading(false);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const [sess, departments] = await Promise.all([
          api.getSession(sessionId),
          api.listDepartments(),
        ]);
        if (cancelled) return;
        setSession(sess);
        const meta = (sess.metadata || {}) as Record<string, unknown>;
        const triage = (meta.triage_classification || {}) as Record<string, unknown>;
        const deptCode = typeof triage.department_code === 'string'
          ? triage.department_code
          : null;
        // Prefer department from recommendation id in metadata if present,
        // otherwise map the engine's department_code. Never surface level/color.
        const deptId = typeof meta.recommended_department_id === 'string'
          ? meta.recommended_department_id
          : null;
        const byId = deptId
          ? departments.find((d) => d.id === deptId)
          : undefined;
        const byCode = deptCode
          ? departments.find((d) => d.code === deptCode)
          : undefined;
        const dept = byId || byCode;
        if (dept) {
          setDepartmentName(
            language === 'th' ? dept.name_th || dept.name_en : dept.name_en,
          );
          setNavLine(
            language === 'th'
              ? dept.nav_line_th || null
              : dept.nav_line_en || null,
          );
        } else if (deptCode) {
          setDepartmentName(deptCode);
          setNavLine(null);
        }
      } catch {
        if (!cancelled) setError(t('slipLoadError'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, language, t]);

  const code = useMemo(() => (sessionId ? slipCode(sessionId) : ''), [sessionId]);
  const meta = (session?.metadata || {}) as Record<string, unknown>;
  const visit = (meta.visit || {}) as Record<string, unknown>;
  const vitals = (meta.vitals || {}) as VitalsMeta;
  const patientName =
    (typeof visit.patient_name === 'string' && visit.patient_name) ||
    getStoredPatientName() ||
    null;
  const visitId =
    (typeof visit.visit_id === 'string' && visit.visit_id) || null;
  const stamped = session?.started_at
    ? new Date(session.started_at).toLocaleString(
        language === 'th' ? 'th-TH' : 'en-GB',
      )
    : '—';

  if (loading) {
    return (
      <main className="slip-page">
        <p className="muted">{t('loading')}</p>
      </main>
    );
  }

  if (error || !session) {
    return (
      <main className="slip-page">
        <p className="error-text">{error || t('slipLoadError')}</p>
      </main>
    );
  }

  return (
    <main className="slip-page">
      <header className="slip-header">
        <p className="slip-hospital">{t('hospitalName')}</p>
        <h1 className="slip-title">{t('slipTitle')}</h1>
        <p className="slip-subtitle muted">{t('slipSubtitle')}</p>
      </header>

      <section className="slip-code-block">
        <span className="slip-label">{t('slipCodeLabel')}</span>
        <strong className="slip-code">{code}</strong>
      </section>

      <dl className="slip-fields">
        <div>
          <dt>{t('slipVisitId')}</dt>
          <dd>{visitId || '—'}</dd>
        </div>
        <div>
          <dt>{t('slipPatientName')}</dt>
          <dd>{patientName || t('slipAnonymous')}</dd>
        </div>
        <div>
          <dt>{t('slipDepartment')}</dt>
          <dd>{departmentName || '—'}</dd>
        </div>
        {navLine && (
          <div>
            <dt>{t('slipNavInstruction')}</dt>
            <dd className="slip-nav-line">{navLine}</dd>
          </div>
        )}
        <div>
          <dt>{t('slipTimestamp')}</dt>
          <dd>{stamped}</dd>
        </div>
      </dl>

      <section className="slip-vitals">
        <h2>{t('slipVitalsTitle')}</h2>
        <div className="slip-vitals-row">
          <div>
            <span>{t('nurseVitalBp')}</span>
            <strong>
              {vitals.systolic && vitals.diastolic
                ? `${vitals.systolic}/${vitals.diastolic}`
                : '—'}
            </strong>
          </div>
          <div>
            <span>{t('nurseVitalPulse')}</span>
            <strong>{formatVital(vitals.pulse_bpm)}</strong>
          </div>
          <div>
            <span>{t('nurseVitalTemp')}</span>
            <strong>{formatVital(vitals.temperature, 1)}</strong>
          </div>
        </div>
        <div className="slip-vitals-row">
          <div>
            <span>{t('nurseVitalWeight')}</span>
            <strong>{formatVital(vitals.weight_kg, 1)}</strong>
          </div>
          <div>
            <span>{t('nurseVitalHeight')}</span>
            <strong>{formatVital(vitals.height_cm)}</strong>
          </div>
          <div>
            <span>{t('nurseVitalBmi')}</span>
            <strong>{formatBmi(vitals.weight_kg, vitals.height_cm)}</strong>
          </div>
        </div>
      </section>

      <p className="slip-print-hint muted">{t('slipPrintHint')}</p>
      <button type="button" className="primary-btn" onClick={() => window.print()}>
        {t('slipPrint')}
      </button>
    </main>
  );
}
