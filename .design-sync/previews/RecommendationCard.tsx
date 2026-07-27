import { RecommendationCard } from 'hospital-hotline-assistant-web';

export const OpdRoutingThai = () => (
  <div style={{ maxWidth: 480 }}>
    <RecommendationCard
      assessment={{
        severity: { level: 'low' },
        department: {
          departmentId: 'opd_general',
          code: 'opd_general',
          name: 'OPD เวชปฏิบัติทั่วไป',
          navLine: 'ชั้น 1 ห้องตรวจ OPD ทั่วไป — เดินตรงจากจุดคัดกรอง เลี้ยวขวาที่เคาน์เตอร์พยาบาล',
        },
      }}
    />
  </div>
);

export const EmergencyRouting = () => (
  <div style={{ maxWidth: 480 }}>
    <RecommendationCard
      assessment={{
        severity: { level: 'emergency' },
        department: {
          departmentId: 'emergency',
          code: 'emergency',
          name: 'Emergency Department',
          navLine: 'Ground floor — follow the red line from the kiosk to the ER entrance.',
        },
      }}
    />
  </div>
);
