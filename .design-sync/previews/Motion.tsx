import * as React from 'react';
import { Mark, NongMali } from '@notuning/mali-ds';
const Wrap = ({ children }: { children: React.ReactNode }) => <div className="mali-root" style={{ padding: 28, display: 'flex', gap: 40, alignItems: 'flex-end', background: 'var(--surface-page)' }}>{children}</div>;
const Cell = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
    {children}
    <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{label}</span>
  </div>
);
export const NongMotions = () => <Wrap>
  <Cell label="nongBloom"><NongMali size={104} motion="nongBloom" /></Cell>
  <Cell label="nongRise"><NongMali size={104} motion="nongRise" /></Cell>
  <Cell label="nongWave"><NongMali size={104} motion="nongWave" /></Cell>
</Wrap>;
export const BudMotions = () => <Wrap>
  <Cell label="budDraw"><Mark size={84} motion="budDraw" /></Cell>
  <Cell label="budFilled"><Mark size={84} motion="budFilled" /></Cell>
  <Cell label="budHand"><Mark size={84} motion="budHand" /></Cell>
  <Cell label="budGrow"><Mark size={84} motion="budGrow" /></Cell>
</Wrap>;
