import * as React from 'react';
import { Mark, Wordmark, Button, Input, Textarea, Select, Field, Card, Badge, Chip, Spinner, Thinking, Stepper, Modal, Toast, DataTable, Orb, KioskQuestion } from '@notuning/mali-ds';
const Wrap = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) => <div className="mali-root" style={{ padding: 24, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', background: 'var(--surface-page)', ...style }}>{children}</div>;
export const Default = () => <Wrap style={{ display: 'block', width: 320 }}><Select defaultValue="im"><option value="em">Emergency</option><option value="im">Internal Medicine</option><option value="or">Orthopedics</option><option value="de">Dermatology</option></Select></Wrap>;
export const Invalid = () => <Wrap style={{ display: 'block', width: 320 }}><Select invalid defaultValue=""><option value="" disabled>Choose a department</option><option>Emergency</option></Select></Wrap>;
