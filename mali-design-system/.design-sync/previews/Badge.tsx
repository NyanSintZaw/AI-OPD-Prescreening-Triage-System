import * as React from 'react';
import { Mark, Wordmark, Button, Input, Textarea, Select, Field, Card, Badge, Chip, Spinner, Thinking, Stepper, Modal, Toast, DataTable, Orb, KioskQuestion } from '@notuning/mali-ds';
const Wrap = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => <div className="mali-root" style={{ padding: 24, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', background: 'var(--surface-page)', ...style }}>{children}</div>;
export const Tones = () => <Wrap><Badge>Pending review</Badge><Badge tone="success">Reviewed</Badge><Badge tone="info">HIS synced</Badge><Badge tone="warning">Needs vitals</Badge><Badge tone="danger">Red flag</Badge><Badge tone="accent">New</Badge></Wrap>;
export const TriageLevels = () => <Wrap><Badge level={1} /><Badge level={2} /><Badge level={3} /><Badge level={4} /><Badge level={5} /></Wrap>;
export const Dots = () => <Wrap><Badge level={1} dot /><Badge level={2} dot /><Badge level={3} dot /><Badge level={4} dot /><Badge level={5} dot /><Badge tone="success" dot /></Wrap>;
