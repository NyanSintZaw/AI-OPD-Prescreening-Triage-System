import * as React from 'react';
import { Mark, Wordmark, Button, Input, Textarea, Select, Field, Card, Badge, Chip, Spinner, Thinking, Stepper, Modal, Toast, DataTable, Orb, KioskQuestion } from '@notuning/mali-ds';
const Wrap = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => <div className="mali-root" style={{ padding: 24, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', background: 'var(--surface-page)', ...style }}>{children}</div>;
export const Default = () => <Wrap style={{ display: 'grid', width: 360 }}><Input placeholder="Search by HN or name" /><Input defaultValue="สมชาย ใจดี" /><Input defaultValue="08123" invalid /><Input placeholder="Disabled" disabled /></Wrap>;
export const Kiosk = () => <Wrap style={{ display: 'block', width: 420 }}><Input size="kiosk" placeholder="66-000000" inputMode="numeric" /></Wrap>;
