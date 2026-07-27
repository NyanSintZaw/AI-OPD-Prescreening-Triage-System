import { ConfirmNameStep } from 'hospital-hotline-assistant-web';

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
    <ConfirmNameStep patientName="สมชาย ใจดี" onConfirm={noop} />
  </div>
);

export const UnclearAnswer = () => (
  <div className="kiosk-root" style={wrap}>
    {freeze}
    <ConfirmNameStep patientName="วรรณา ศรีสุวรรณ" unclear onConfirm={noop} />
  </div>
);

export const Busy = () => (
  <div className="kiosk-root" style={wrap}>
    {freeze}
    <ConfirmNameStep patientName="สมชาย ใจดี" busy onConfirm={noop} />
  </div>
);
