import { PatientIdPassPopup } from 'hospital-hotline-assistant-web';

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

// .patient-id-popup-launcher right-aligns inside its container — constrain
// the cell width so the button doesn't float at the far edge of the sheet.
export const LauncherSecondary = () => (
  <div style={{ maxWidth: 300 }}>
    <PatientIdPassPopup sessionId={sessionId} language="th" assessment={assessment} />
  </div>
);

export const LauncherPrimary = () => (
  <div style={{ maxWidth: 300 }}>
    <PatientIdPassPopup
      sessionId={sessionId}
      language="th"
      assessment={assessment}
      triggerVariant="primary"
    />
  </div>
);

// autoOpenKey opens the modal on mount. The modal is position:fixed — the
// transformed wrapper turns the wrapper into its containing block so the
// overlay stays inside this cell instead of covering the whole sheet.
export const ModalOpen = () => (
  <div
    style={{
      position: 'relative',
      transform: 'translateZ(0)',
      width: 760,
      height: 560,
      overflow: 'hidden',
      borderRadius: 12,
    }}
  >
    <PatientIdPassPopup
      sessionId={sessionId}
      language="th"
      assessment={assessment}
      autoOpenKey="preview"
    />
  </div>
);
