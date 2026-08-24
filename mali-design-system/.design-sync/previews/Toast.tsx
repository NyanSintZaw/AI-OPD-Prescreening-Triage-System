import * as React from 'react';
import { Mark, Wordmark, Button, Input, Textarea, Select, Field, Card, Badge, Chip, Spinner, Thinking, Stepper, Modal, Toast, DataTable, Orb, KioskQuestion } from '@notuning/mali-ds';
const Wrap = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => <div className="mali-root" style={{ padding: 24, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', background: 'var(--surface-page)', ...style }}>{children}</div>;
export const Success = () => <Wrap><Toast tone="success" title="Review saved" description="Session 8f3a → Internal Medicine" onDismiss={() => {}} /></Wrap>;
export const Danger = () => <Wrap><Toast tone="danger" title="HIS write-back failed" description="Retry now or save locally." action={{ label: 'Retry', onClick: () => {} }} onDismiss={() => {}} /></Wrap>;
export const Neutral = () => <Wrap><Toast title="Criteria v2 published" description="New sessions pin version 2." /></Wrap>;
