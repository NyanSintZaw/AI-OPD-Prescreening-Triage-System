import * as React from 'react';
import { Mark, Wordmark, Button, Input, Textarea, Select, Field, Card, Badge, Chip, Spinner, Thinking, Stepper, Modal, Toast, DataTable, Orb, KioskQuestion } from '@notuning/mali-ds';
const Wrap = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => <div className="mali-root" style={{ padding: 24, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', background: 'var(--surface-page)', ...style }}>{children}</div>;
export const States = () => <Wrap style={{ gap: 40 }}><Orb state="idle" /><Orb state="listening" level={0.7} /><Orb state="thinking" /><Orb state="speaking" level={0.5} /></Wrap>;
export const IdleHero = () => <Wrap style={{ display: 'grid', justifyItems: 'center', gap: 32, padding: 48 }}><Orb size={240} /><Wordmark height={36} product="Prescreening" /></Wrap>;
