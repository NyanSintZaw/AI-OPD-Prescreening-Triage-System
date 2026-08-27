import { FILLS, unfilledCount } from '../content/fills';

/**
 * PITCH_DECK §5's register table, rendered from the same data the slides read,
 * so it cannot drift from what is actually on them.
 *
 * The rule this screen exists to enforce: never ship the deck with a visible
 * [FILL]. Either the number, or the sentence "to be measured in the pilot".
 * A bracket on the projector is not an option.
 */
export function FillAudit() {
  const rows = Object.entries(FILLS);
  const missing = unfilledCount();

  return (
    <div className="d-screen">
      <h1 className="d-screen-title">The [FILL] register</h1>
      <p className={`d-screen-lead${missing ? ' is-warn' : ' is-ok'}`}>
        {rows.length === 0
          ? 'Nothing outstanding — no slide currently shows a [FILL].'
          : missing
            ? `${missing} of ${rows.length} still empty. Never present with a visible [FILL] — either the number, or the sentence "to be measured in the pilot".`
            : `All ${rows.length} filled. Ready to present.`}
      </p>

      <table className="d-audit">
        <thead>
          <tr>
            <th>Number</th>
            <th>Value</th>
            <th>Slides</th>
            <th>How to get it</th>
            <th>Owner</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([key, f]) => (
            <tr key={key} className={f.value == null ? 'is-missing' : ''}>
              <td>
                {f.label}
                <code>{key}</code>
              </td>
              <td>
                {f.value == null ? <span className="d-fill">[FILL]</span> : String(f.value)}
                {f.caveat && <em className="d-audit-caveat">{f.caveat}</em>}
              </td>
              <td>{f.slides.join(', ')}</td>
              <td>{f.source}</td>
              <td>{f.owner ?? <span className="d-audit-unassigned">unassigned</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
