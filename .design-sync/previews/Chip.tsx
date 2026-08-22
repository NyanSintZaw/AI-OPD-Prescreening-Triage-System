import * as React from 'react';
import { Mark, Wordmark, Button, Input, Textarea, Select, Field, Card, Badge, Chip, Spinner, Thinking, Stepper, Modal, Toast, DataTable, Orb, KioskQuestion } from '@notuning/mali-ds';
const Wrap = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => <div className="mali-root" style={{ padding: 24, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', background: 'var(--surface-page)', ...style }}>{children}</div>;
export const Tags = () => <Wrap><Chip>ไข้</Chip><Chip selected>ไอ</Chip><Chip>เจ็บคอ</Chip><Chip onRemove={() => {}}>ปวดหัว</Chip></Wrap>;
export const KioskAnswers = () => <Wrap><Chip size="kiosk">ใช่</Chip><Chip size="kiosk" selected>ไม่ใช่</Chip><Chip size="kiosk">มากกว่า 3 วัน</Chip></Wrap>;
