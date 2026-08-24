import * as React from 'react';
import { NongMali } from '@notuning/mali-ds';
const Wrap = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => <div className="mali-root" style={{ padding: 24, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', background: 'var(--surface-page)', ...style }}>{children}</div>;
export const Sizes = () => <Wrap style={{ gap: 32 }}><NongMali size={80} /><NongMali size={140} /></Wrap>;
export const Welcome = () => <Wrap style={{ justifyContent: 'center', padding: 40 }} ><div style={{ textAlign: 'center' }}><NongMali size={140} /><div style={{ fontSize: 24, fontWeight: 700, color: 'var(--text-heading)', marginTop: 16 }}>สวัสดีค่ะ ฉันชื่อมะลิ</div><div style={{ fontSize: 14, color: 'var(--text-muted)', marginTop: 6 }}>Hello, I'm Mali</div></div></Wrap>;
