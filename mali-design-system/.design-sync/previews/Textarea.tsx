import * as React from 'react';
import { Mark, Wordmark, Button, Input, Textarea, Select, Field, Card, Badge, Chip, Spinner, Thinking, Stepper, Modal, Toast, DataTable, Orb, KioskQuestion } from '@notuning/mali-ds';
const Wrap = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => <div className="mali-root" style={{ padding: 24, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', background: 'var(--surface-page)', ...style }}>{children}</div>;
export const Default = () => <Wrap style={{ display: 'block', width: 420 }}><Textarea placeholder="Nurse notes…" /></Wrap>;
export const Filled = () => <Wrap style={{ display: 'block', width: 420 }}><Textarea defaultValue="Patient reports intermittent chest tightness since 06:30, worse on exertion. No prior cardiac history." rows={4} /></Wrap>;
