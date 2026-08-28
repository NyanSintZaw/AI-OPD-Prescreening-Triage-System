import { Block } from '../deck/Block';
import { SlideHeadline } from '../deck/SlideHeadline';
import { Mark } from '../design-system/components/Mark';
import type { Slide } from '../content/types';

/**
 * The whole deployment-prep section on one slide: what the hospital's IT needs
 * to decide, what data we ask for, and what it runs on.
 *
 * This is a reference slide. Hospital IT photographs it rather than reading it
 * aloud, so it is deliberately dense — the job is to be complete and specific,
 * not to be skimmable from the back row.
 *
 * Two things earn their space. The `badge` says plainly that single sign-on is
 * not built yet, which costs a sentence here and costs a pilot if omitted. And
 * the VRAM `rows` under the GPU item are measured against a real card — that
 * table is what turns "runs on your hardware" from a claim into a spec.
 */
export function ChecklistSlide({ slide }: { slide: Extract<Slide, { layout: 'checklist' }> }) {
  return (
    <div className="d-check">
      <Block className="d-eyebrow">
        <Mark size={34} motion="budHand" />
        <span className="d-eyebrow-en" lang="en">
          {slide.eyebrow.en}
        </span>
      </Block>

      <SlideHeadline headline={slide.headline} size="title" />

      <div className="d-check-cols">
        {slide.columns.map((col) => (
          <Block key={col.title} className="d-check-col">
            <h2 className="d-check-col-title">{col.title}</h2>
            <ul>
              {col.items.map((item) => (
                <li key={item.title} className={item.kind === 'endpoint' ? 'is-endpoint' : undefined}>
                  {item.kind !== 'endpoint' && (
                    <span className="d-check-dash" aria-hidden="true">
                      —
                    </span>
                  )}
                  <span className="d-check-item">
                    <span className="d-check-head">
                      <span className="d-check-title">{item.title}</span>
                      {item.badge && <span className="d-check-badge">{item.badge}</span>}
                    </span>
                    {item.body && <span className="d-check-body">{item.body}</span>}

                    {item.terms && (
                      <span className="d-check-terms">
                        {item.terms.map((t) => (
                          <span key={t.term} className="d-check-term">
                            <b>{t.term}</b>
                            <span>{t.gloss}</span>
                          </span>
                        ))}
                      </span>
                    )}

                    {item.rows && (
                      <span className="d-check-rows">
                        {item.rows.map((r) => (
                          <span
                            key={r.label}
                            className={r.total ? 'd-check-row is-total' : 'd-check-row'}
                          >
                            <span className="d-check-row-label">{r.label}</span>
                            <span className="d-check-row-name">{r.name}</span>
                            <span className="d-check-row-value">{r.value}</span>
                          </span>
                        ))}
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </Block>
        ))}
      </div>

      <Block className="d-check-footer">
        <p lang="en">{slide.footer}</p>
      </Block>
    </div>
  );
}
