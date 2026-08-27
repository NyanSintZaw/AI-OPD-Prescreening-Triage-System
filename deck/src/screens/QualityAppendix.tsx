import { FACTS, type Fact } from '../content/facts';

/**
 * Off the 9-minute flow, reachable on `V`. This is the answer to "can you
 * prove it?" in Q&A, and every number arrives with the caveat the evaluation
 * doc insists it travels with — a wide interval stated out loud is stronger
 * than a point estimate a clinician can puncture.
 */
const SHOWN = ['undertriage', 'qwk', 'extractionEval', 'validatorLeaks', 'unitTests'] as const;

export function QualityAppendix() {
  return (
    <div className="d-screen">
      <h1 className="d-screen-title">Measured quality</h1>
      <p className="d-screen-lead">
        Appendix — not part of the nine minutes. Every figure below measures the pipeline
        against the criteria&apos;s own reference labels. None of it is a clinical claim.
      </p>

      <div className="d-quality">
        {SHOWN.map((k) => {
          /* Widen off the `as const` literal so the optional fields are visible. */
          const f: Fact = FACTS[k];
          return (
            <figure key={k} className="d-quality-item">
              <strong>{f.display ?? f.value}</strong>
              <figcaption>
                <span className="d-quality-label" lang="en">
                  {f.label.en}
                </span>
                <span className="d-quality-source">{f.source}</span>
                {f.caveat && <em className="d-quality-caveat">{f.caveat}</em>}
              </figcaption>
            </figure>
          );
        })}
      </div>

      <p className="d-screen-foot">
        What we do not claim: that this architecture is more accurate than an end-to-end
        model. The honest justification is auditability, determinism and version control.
      </p>
    </div>
  );
}
