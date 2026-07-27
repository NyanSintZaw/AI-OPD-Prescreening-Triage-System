import { PatientIdPass } from 'hospital-hotline-assistant-web';

// Realistic completed booth session — routes to OPD General Medicine.
const assessment = {
  severity: { level: 'low' as const },
  department: {
    departmentId: 'opd_general',
    code: 'opd_general',
    name: 'OPD เวชปฏิบัติทั่วไป',
    navLine: 'ชั้น 1 ห้องตรวจ OPD ทั่วไป — เดินตรงจากจุดคัดกรอง เลี้ยวขวาที่เคาน์เตอร์พยาบาล',
  },
};

const sessionId = '7f3a9c2e-4b1d-4e0a-9c31-8d2f6a5b1e47';

export const PanelWithAssessment = () => (
  <div style={{ maxWidth: 640 }}>
    <PatientIdPass sessionId={sessionId} language="th" assessment={assessment} variant="panel" />
  </div>
);

export const PanelAwaitingAssessment = () => (
  <div style={{ maxWidth: 640 }}>
    <PatientIdPass sessionId="990000000000000001" language="th" assessment={null} variant="panel" />
  </div>
);

export const Compact = () => (
  <div style={{ maxWidth: 420 }}>
    <PatientIdPass sessionId={sessionId} language="th" assessment={assessment} variant="compact" />
  </div>
);
