const KEYS: [string, string][] = [
  ['-> / Space / PageDown', 'next slide'],
  ['<- / PageUp', 'previous slide'],
  ['Home / End', 'first / last'],
  ['1 - 9, 0', 'jump to slide'],
  ['O', 'overview grid'],
  ['N', 'presenter notes'],
  ['F', 'fullscreen'],
  ['T / R', 'start-pause / reset the timer'],
  ['B or .', 'blackout'],
  ['A', 'the [FILL] register'],
  ['Q', 'Q&A appendix'],
  ['V', 'measured quality numbers'],
  ['M', 'force motion (overrides reduced motion)'],
  ['?', 'this list'],
  ['Esc', 'close an overlay'],
];

export function HelpOverlay({ onClose }: { onClose: () => void }) {
  return (
    <div className="d-overlay" onClick={onClose} role="presentation">
      <div className="d-help">
        <h2>Keys</h2>
        <dl>
          {KEYS.map(([k, what]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{what}</dd>
            </div>
          ))}
        </dl>
        <p className="d-help-foot">
          PageUp and PageDown are what a wireless presenter remote sends.
        </p>
      </div>
    </div>
  );
}
