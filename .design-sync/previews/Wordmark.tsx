import * as React from 'react';
import { Mark, Wordmark, Button, Input, Textarea, Select, Field, Card, Badge, Chip, Spinner, Thinking, Stepper, Modal, Toast, DataTable, Orb, KioskQuestion } from '@notuning/mali-ds';
const Wrap = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => <div className="mali-root" style={{ padding: 24, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', background: 'var(--surface-page)', ...style }}>{children}</div>;
export const Default = () => <Wrap><Wordmark /></Wrap>;
export const WithProduct = () => <Wrap><Wordmark height={28} product="Prescreening" /></Wrap>;
export const Kiosk = () => <Wrap><Wordmark height={44} product="Prescreening" /></Wrap>;
