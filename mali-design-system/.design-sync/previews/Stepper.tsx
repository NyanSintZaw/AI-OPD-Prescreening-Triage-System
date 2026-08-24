import * as React from 'react';
import { Mark, Wordmark, Button, Input, Textarea, Select, Field, Card, Badge, Chip, Spinner, Thinking, Stepper, Modal, Toast, DataTable, Orb, KioskQuestion } from '@notuning/mali-ds';
const Wrap = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => <div className="mali-root" style={{ padding: 24, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', background: 'var(--surface-page)', ...style }}>{children}</div>;
export const Portal = () => <Wrap><Stepper steps={['Language', 'HN', 'Vitals', 'Interview', 'Slip']} current={2} /></Wrap>;
export const Kiosk = () => <Wrap style={{ display: 'block' }}><Stepper size="kiosk" steps={['ภาษา', 'HN', 'วัดสัญญาณชีพ', 'สัมภาษณ์', 'ใบนัด']} current={3} /></Wrap>;
export const Start = () => <Wrap><Stepper steps={['Language', 'HN', 'Vitals', 'Interview', 'Slip']} current={0} /></Wrap>;
