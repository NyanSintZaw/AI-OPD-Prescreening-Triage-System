import * as React from 'react';
import { Mark, Wordmark, Button, Input, Textarea, Select, Field, Card, Badge, Chip, Spinner, Thinking, Stepper, Modal, Toast, DataTable, Orb, KioskQuestion } from '@notuning/mali-ds';
const Wrap = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => <div className="mali-root" style={{ padding: 24, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', background: 'var(--surface-page)', ...style }}>{children}</div>;
export const WithHint = () => <Wrap style={{ display: 'block', width: 360 }}><Field label="Hospital number (HN)" htmlFor="hn" hint="8 digits, printed on the patient card" required><Input id="hn" placeholder="66-000000" /></Field></Wrap>;
export const WithError = () => <Wrap style={{ display: 'block', width: 360 }}><Field label="Phone" htmlFor="ph" error="Enter 10 digits, e.g. 0812345678"><Input id="ph" defaultValue="08123" invalid /></Field></Wrap>;
export const Form = () => <Wrap style={{ display: 'grid', gap: 20, width: 360 }}>
  <Field label="Department" htmlFor="d"><Select id="d"><option>Internal Medicine</option><option>Emergency</option></Select></Field>
  <Field label="Review note" htmlFor="n" hint="Visible to the admin, not the patient"><Textarea id="n" rows={3} /></Field>
  <Button>Save review</Button></Wrap>;
