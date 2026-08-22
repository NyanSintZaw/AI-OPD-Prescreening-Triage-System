import * as React from 'react';
import { Mark, Wordmark, Button, Input, Textarea, Select, Field, Card, Badge, Chip, Spinner, Thinking, Stepper, Modal, Toast, DataTable, Orb, KioskQuestion } from '@notuning/mali-ds';
const Wrap = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => <div className="mali-root" style={{ padding: 24, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', background: 'var(--surface-page)', ...style }}>{children}</div>;
const rows = [
  { hn: '66-012345', name: 'สมชาย ใจดี', age: 58, level: 2, dept: 'Emergency', time: '09:12' },
  { hn: '66-018822', name: 'Nattaya K.', age: 34, level: 4, dept: 'Internal Medicine', time: '09:15' },
  { hn: '66-020101', name: 'วิภา ศรีสุข', age: 71, level: 3, dept: 'Orthopedics', time: '09:21' },
  { hn: '66-021560', name: 'Peter L.', age: 26, level: 5, dept: 'Dermatology', time: '09:24' },
];
const cols = [
  { key: 'hn', header: 'HN' }, { key: 'name', header: 'Patient' }, { key: 'age', header: 'Age', align: 'right' as const },
  { key: 'level', header: 'Triage', render: (r: typeof rows[number]) => <Badge level={r.level as 1} /> },
  { key: 'dept', header: 'Department' }, { key: 'time', header: 'Time', align: 'right' as const },
];
export const ReviewQueue = () => <Wrap style={{ display: 'block', width: 760 }}><DataTable caption="Review queue" density="compact" rows={rows} columns={cols} rowKey={(r) => r.hn} onRowClick={() => {}} /></Wrap>;
export const Empty = () => <Wrap style={{ display: 'block', width: 760 }}><DataTable rows={[]} columns={cols} rowKey={(r) => r.hn} empty="No sessions waiting for review." /></Wrap>;
