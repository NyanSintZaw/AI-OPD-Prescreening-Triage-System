import { VisitIdCapture } from 'hospital-hotline-assistant-web';

const noop = () => {};
const wrap = { position: 'relative' as const, inset: 'auto', overflow: 'visible', padding: 24 };
// Capture freezes the clock, so framer-motion never leaves its initial
// opacity-0/offset state — force inline motion styles to their settled values.
const freeze = (
  <style>{`.kiosk-root [style*="opacity"] { opacity: 1 !important; }
.kiosk-root [style*="transform:"] { transform: none !important; }`}</style>
);

const base = {
  onSubmit: noop,
  onSkip: noop,
  linking: false,
  notFound: false,
  linkError: false,
};

export const Default = () => (
  <div className="kiosk-root" style={wrap}>
    {freeze}
    <VisitIdCapture language="th" {...base} />
  </div>
);

export const NotFound = () => (
  <div className="kiosk-root" style={wrap}>
    {freeze}
    <VisitIdCapture language="th" {...base} notFound />
  </div>
);

export const LinkError = () => (
  <div className="kiosk-root" style={wrap}>
    {freeze}
    <VisitIdCapture language="th" {...base} linkError />
  </div>
);

export const IdentityRejected = () => (
  <div className="kiosk-root" style={wrap}>
    {freeze}
    <VisitIdCapture language="th" {...base} identityRejected />
  </div>
);
