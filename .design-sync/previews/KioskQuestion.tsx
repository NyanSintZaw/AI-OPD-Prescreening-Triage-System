import * as React from 'react';
import { Mark, Wordmark, Button, Input, Textarea, Select, Field, Card, Badge, Chip, Spinner, Thinking, Stepper, Modal, Toast, DataTable, Orb, KioskQuestion } from '@notuning/mali-ds';
const Wrap = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => <div className="mali-root" style={{ padding: 24, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', background: 'var(--surface-page)', ...style }}>{children}</div>;
export const Thai = () => <Wrap style={{ display: 'block', padding: 48 }}><KioskQuestion question="อาการปวดหัวเป็นมานานแค่ไหนแล้วคะ?" caption="ประมาณสามวันแล้วครับ ปวดตุบๆ" /></Wrap>;
export const English = () => <Wrap style={{ display: 'block', padding: 48 }}><KioskQuestion lang="en" question="Do you have any chest pain right now?" /></Wrap>;
export const WithOrb = () => <Wrap style={{ display: 'grid', justifyItems: 'center', gap: 40, padding: 48 }}><Orb state="listening" level={0.4} /><KioskQuestion question="วันนี้มาด้วยอาการอะไรคะ?" /><div style={{ display: 'flex', gap: 12 }}><Chip size="kiosk">ไข้</Chip><Chip size="kiosk">ไอ</Chip><Chip size="kiosk">ปวดท้อง</Chip></div></Wrap>;
