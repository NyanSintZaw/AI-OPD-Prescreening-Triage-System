import * as React from 'react';
import { Mark, Wordmark, Button, Input, Textarea, Select, Field, Card, Badge, Chip, Spinner, Thinking, Stepper, Modal, Toast, DataTable, Orb, KioskQuestion } from '@notuning/mali-ds';
const Wrap = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => <div className="mali-root" style={{ padding: 24, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', background: 'var(--surface-page)', ...style }}>{children}</div>;
export const Variants = () => <Wrap><Button>Confirm</Button><Button variant="secondary">Back</Button><Button variant="ghost">Skip</Button><Button variant="danger">Escalate</Button></Wrap>;
export const Sizes = () => <Wrap><Button size="sm">Small</Button><Button>Medium</Button><Button size="lg">Large</Button><Button size="kiosk">เริ่มคัดกรอง</Button></Wrap>;
export const States = () => <Wrap><Button loading>Saving</Button><Button disabled>Disabled</Button><Button variant="secondary" loading>Loading</Button></Wrap>;
export const Block = () => <Wrap style={{ display: 'block', width: 360 }}><Button block size="kiosk">ยืนยัน</Button></Wrap>;
