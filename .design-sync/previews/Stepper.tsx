import { Stepper } from 'hospital-hotline-assistant-web';

/* The stepper lives in the white kiosk top bar — white band mimics that
 * context; kiosk-root supplies the .k-* tokens. */
const Band = ({ children }: { children?: any }) => (
  <div
    className="kiosk-root"
    // .kiosk-root is position:fixed inset:0 (full kiosk canvas) — pin it
    // back into the preview cell and let content size it.
    style={{ position: 'relative', overflow: 'visible', padding: 24, background: '#ffffff' }}
  >
    {children}
  </div>
);

export const StepIdentify = () => (
  <Band>
    <Stepper current={0} />
  </Band>
);

export const StepSymptoms = () => (
  <Band>
    <Stepper current={1} />
  </Band>
);

export const StepResult = () => (
  <Band>
    <Stepper current={2} />
  </Band>
);
