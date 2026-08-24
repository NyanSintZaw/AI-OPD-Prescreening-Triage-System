import * as React from 'react';
import { Mark } from '@notuning/mali-ds';
const Wrap = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => <div className="mali-root" style={{ padding: 24, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', background: 'var(--surface-page)', ...style }}>{children}</div>;
export const Sizes = () => <Wrap style={{ gap: 24 }}><Mark size={24} /><Mark size={48} /><Mark size={96} /></Wrap>;
export const Stages = () => <Wrap style={{ gap: 24 }}><Mark size={64} stage={0} /><Mark size={64} stage={1} /><Mark size={64} stage={3} /></Wrap>;
