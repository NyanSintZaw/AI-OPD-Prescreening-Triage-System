import * as React from 'react';
import { Wordmark } from '@notuning/mali-ds';
const Wrap = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => <div className="mali-root" style={{ padding: 24, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', background: 'var(--surface-page)', ...style }}>{children}</div>;
export const Default = () => <Wrap><Wordmark /></Wrap>;
export const CompactBud = () => <Wrap><Wordmark height={20} mark="bud" /></Wrap>;
export const Thai = () => <Wrap><Wordmark height={28} lang="th" /></Wrap>;
export const Friendly = () => <Wrap style={{ gap: 24 }}><Wordmark height={28} friendly /><Wordmark height={28} lang="th" friendly /></Wrap>;
export const WithProduct = () => <Wrap><Wordmark height={28} product="Prescreening" /></Wrap>;
export const OnDark = () => <div className="mali-root" style={{ padding: 24, display: 'flex', gap: 24, alignItems: 'center', background: 'var(--teal-700)' }}><Wordmark height={28} tone="dark" /><Wordmark height={28} lang="th" friendly tone="dark" /></div>;
