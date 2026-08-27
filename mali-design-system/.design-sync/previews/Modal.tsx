import * as React from 'react';
import { Mark, Wordmark, Button, Input, Textarea, Select, Field, Card, Badge, Chip, Spinner, Thinking, Stepper, Modal, Toast, DataTable, Orb, KioskQuestion } from '@notuning/mali-ds';
const Wrap = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => <div className="mali-root" style={{ padding: 24, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', background: 'var(--surface-page)', ...style }}>{children}</div>;
export const Confirm = () => <div className="mali-root" style={{ position: 'relative', width: 640, height: 400, background: 'var(--surface-page)' }}>
  <style>{'.mali-modal__backdrop{position:absolute}'}</style>
  <Modal open onClose={() => {}} title="Escalate to nurse?" actions={<><Button variant="secondary">Cancel</Button><Button variant="danger">Escalate</Button></>}>
    <p>The patient will be flagged for immediate nurse review. This can't be undone from the kiosk.</p>
  </Modal></div>;
