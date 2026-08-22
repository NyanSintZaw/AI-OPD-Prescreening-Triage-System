import * as React from 'react';
import { Mark, Wordmark, Button, Input, Textarea, Select, Field, Card, Badge, Chip, Spinner, Thinking, Stepper, Modal, Toast, DataTable, Orb, KioskQuestion } from '@notuning/mali-ds';
const Wrap = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => <div className="mali-root" style={{ padding: 24, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', background: 'var(--surface-page)', ...style }}>{children}</div>;
export const Line = () => <Wrap style={{ gap: 24 }}><Mark size={20} /><Mark size={32} /><Mark size={48} /></Wrap>;
export const Glow = () => <Wrap style={{ gap: 24 }}><Mark size={48} variant="glow" /><Mark size={96} variant="glow" /></Wrap>;
