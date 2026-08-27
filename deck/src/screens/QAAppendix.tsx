import { QA } from '../content/qa';

/**
 * Off the nine minutes, on `Q`. Both languages side by side, because the deck
 * guide's rule is to answer in the asker's language and you do not want to be
 * translating under pressure.
 */
export function QAAppendix() {
  return (
    <div className="d-screen">
      <h1 className="d-screen-title">Q&amp;A</h1>
      <p className="d-screen-lead">
        Answer in the asker&apos;s language. Two sentences. Decide who takes each one before
        you go on.
      </p>

      <div className="d-qa">
        {QA.map((e) => (
          <article key={e.q.en} className={`d-qa-item${e.verify ? ' is-verify' : ''}`}>
            <h2 lang="th">{e.q.th}</h2>
            <p className="d-qa-q-en" lang="en">
              {e.q.en}
            </p>
            <p className="d-qa-a" lang="th">
              {e.a.th}
            </p>
            <p className="d-qa-a d-qa-a--en" lang="en">
              {e.a.en}
            </p>
            {e.verify && <p className="d-qa-flag">Verify against the running system first.</p>}
            {e.hasDemo && <p className="d-qa-demo">{e.hasDemo}</p>}
          </article>
        ))}
      </div>
    </div>
  );
}
