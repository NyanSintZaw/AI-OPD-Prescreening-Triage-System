import { HistoryIntakeStep } from 'hospital-hotline-assistant-web';

const noop = () => {};
const wrap = { position: 'relative' as const, inset: 'auto', overflow: 'visible', padding: 24 };
// Capture freezes the clock, so framer-motion never leaves its initial
// opacity-0/offset state — force inline motion styles to their settled values.
const freeze = (
  <style>{`.kiosk-root [style*="opacity"] { opacity: 1 !important; }
.kiosk-root [style*="transform:"] { transform: none !important; }
.kiosk-root input { font-family: var(--k-font); }`}</style>
);

export const Default = () => (
  <div className="kiosk-root" style={wrap}>
    {freeze}
    <HistoryIntakeStep onSubmit={noop} onSkip={noop} />
  </div>
);

export const SaveError = () => (
  <div className="kiosk-root" style={wrap}>
    {freeze}
    <HistoryIntakeStep error onSubmit={noop} onSkip={noop} />
  </div>
);

export const Saving = () => (
  <div className="kiosk-root" style={wrap}>
    {freeze}
    <HistoryIntakeStep busy onSubmit={noop} onSkip={noop} />
  </div>
);
