import { FILLS } from '../content/fills';
import { SLIDES } from '../content/slides';

/**
 * PITCH_DECK §7's last checklist item: the one page that circulates after you
 * leave the room — the three-operation integration table, the hardware line
 * items, and the pricing tiers.
 *
 * Composed from the SAME slide objects the deck renders, so it cannot drift
 * from what was presented. Print it with Ctrl+P, A4 portrait, background
 * graphics on.
 */
function slideOf(id: string) {
  return SLIDES.find((s) => s.id === id);
}

export function LeaveBehind() {
  const business = slideOf('business');
  const prep = slideOf('prep');
  const missing = Object.values(FILLS).filter((f) => f.value == null).length;

  return (
    <div className="d-leave">
      <header className="d-leave-head">
        <h1>AI OPD Pre-Screening Booth</h1>
        <p lang="th">บูธคัดกรองผู้ป่วยนอกด้วย AI</p>
      </header>

      {missing > 0 && (
        <p className="d-leave-warn">
          {missing} value{missing === 1 ? '' : 's'} still unfilled — do not hand this page out
          until the register at #/audit is empty.
        </p>
      )}

      {prep?.layout === 'checklist' && (
        <>
          {prep.columns.map((col) => (
            <section key={col.title}>
              <h2>{col.title}</h2>
              <table>
                <tbody>
                  {col.items.map((item) => (
                    <tr key={item.title}>
                      <th scope="row">
                        {item.kind === 'endpoint' ? <code>{item.title}</code> : item.title}
                        {item.badge && <code>{item.badge}</code>}
                      </th>
                      <td>
                        {item.body}
                        {/* The VRAM budget is exactly what procurement wants on
                            paper, so it survives into the PDF. */}
                        {item.rows && (
                          <div className="d-leave-spec">
                            {item.rows.map((r) => (
                              <div key={r.label}>
                                <b>{r.label}</b>
                                <span>{r.name}</span>
                                <em>{r.value}</em>
                              </div>
                            ))}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ))}
          <p className="d-leave-note">{prep.footer}</p>
        </>
      )}

      {business?.layout === 'business' && (
        <section>
          <h2>How it is bought</h2>
          <table>
            <tbody>
              {business.tiers.map((tier, i) => (
                <tr key={tier.label}>
                  <th scope="row">
                    {String(i + 1).padStart(2, '0')} · {tier.label}
                    {tier.badge && <code>{tier.badge}</code>}
                  </th>
                  <td>
                    {tier.price.map((p) => (
                      <div key={p.figure}>
                        <strong>{p.figure}</strong> {p.unit}
                      </div>
                    ))}
                  </td>
                  <td>
                    {tier.lines.join('; ')}
                    <div className="d-leave-note">{tier.muted}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {/* The line that keeps an estimate from reading as a finding. */}
          <p className="d-leave-note">{business.caveat}</p>
        </section>
      )}
    </div>
  );
}
