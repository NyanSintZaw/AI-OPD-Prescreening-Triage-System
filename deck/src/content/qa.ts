/**
 * PITCH_DECK §6 — the questions this room always asks, with the answer
 * prepared in both languages and short enough to actually say. Off the flow;
 * reachable on `Q`.
 *
 * One entry is deliberately unfinished: "what if the network or the HIS is
 * down" is marked `verify` because the deck guide says to check the current
 * behaviour rather than improvise, and nobody has. Do not fill it from memory.
 */
export interface QaEntry {
  q: { th: string; en: string };
  a: { th: string; en: string };
  /** Answer this from the running system before the pitch, not from the deck. */
  verify?: boolean;
  /** Have this tab open, but do not show it unprompted. */
  hasDemo?: string;
}

export const QA: QaEntry[] = [
  {
    q: { th: 'ถ้า AI ตัดสินผิดล่ะ', en: 'What if the AI is wrong?' },
    a: {
      th: 'AI ไม่ได้เป็นคนตัดสิน มันสกัดอาการจากคำพูดเท่านั้น ระดับความเร่งด่วนและแผนกตัดสินด้วยกฎที่เข้ารหัสจากคู่มือของโรงพยาบาลเอง และพยาบาลตรวจทานทุกเคสก่อนบันทึกลงระบบ',
      en: 'The AI does not decide. It extracts findings from speech; deterministic rules encoded from your manual decide the level and department, and a nurse reviews every case before anything is published to the record.',
    },
  },
  {
    q: { th: 'ระบบวินิจฉัยโรคไหม', en: 'Does it diagnose?' },
    a: {
      th: 'ไม่ — ระบบจัดลำดับความเร่งด่วนและส่งต่อแผนกเท่านั้น ผู้ป่วยไม่เห็นระดับ สี การวินิจฉัย หรือชื่อยา และทุกคำตอบถูกตรวจหาการรั่วไหลทั้งสองภาษา',
      en: 'No — it routes and prioritises. Patients never see a level, colour, diagnosis or prescription; every reply is validated against leaks in both languages.',
    },
  },
  {
    q: { th: 'เสียงของผู้ป่วยไปไหน', en: 'Where does patient audio go?' },
    a: {
      th: 'ในระบบจริง ไม่ไปไหนเลย — LLM, STT และ TTS ทำงานบนเครื่องของโรงพยาบาล ในการสาธิตนี้ใช้ Google Cloud และไม่มีข้อมูลระบุตัวตนผู้ป่วยส่งถึงโมเดลเลย มีเทสต์ที่ทำให้ build ล้มถ้าหลุด',
      en: 'In production, nowhere — local LLM, STT and TTS on hospital hardware. This demo uses Google Cloud, and no patient identifier ever reaches the model: a test fails the build if one does.',
    },
  },
  {
    q: { th: 'ผู้สูงอายุจะใช้ตู้ไม่เป็น', en: 'Elderly patients will not use a kiosk.' },
    a: {
      th: 'ทุกคำถามมีปุ่มตอบเร็วให้แตะ และมีทางเลือกพิมพ์ เจ้าหน้าที่ยังช่วยได้เหมือนเดิม — บูธลดงานซักประวัติ ไม่ได้ลดคน',
      en: 'Every question also renders tappable quick-reply chips, and a typed fallback exists. Staff assistance is unchanged — the booth removes intake work, not people.',
    },
  },
  {
    q: { th: 'ถ้าจะแก้เกณฑ์คัดกรองต้องทำอย่างไร', en: 'How do we change the criteria?' },
    a: {
      th: 'อัปโหลด → ฉบับร่าง → ตรวจทาน → อนุมัติ → เปิดใช้ พร้อมเลขเวอร์ชัน แต่ละเซสชันบันทึกว่าใช้เวอร์ชันไหน ผลเก่าจึงยังตรวจสอบย้อนหลังได้ เป็นการเปลี่ยนเชิงนโยบาย ไม่ใช่การแก้โค้ด',
      en: 'Upload, draft, review, approve, activate — with version numbers. Each session records the version it used, so old results stay auditable. It is a governance change, not a code change.',
    },
  },
  {
    q: { th: 'สำเนียงหรือภาษาถิ่นล่ะ', en: 'Thai accents and dialects?' },
    a: {
      th: 'ระบบรับมือสำเนียงเหนือและคำพูดแบบชาวบ้านได้ในการทดสอบที่ผ่านมา แต่ขอบเขตยังจำกัด — เราเสนอให้ทดสอบสำเนียงเป็นงานหนึ่งในช่วงนำร่อง',
      en: 'It handled Northern dialect and colloquial phrasing in our probes, but the coverage is limited and we will say so. We propose accent testing as a pilot task.',
    },
    hasDemo: 'Run 5 — a Thai live call, if not already shown',
  },
  {
    q: {
      th: 'ถ้าเครือข่ายหรือ HIS ล่มจะเป็นอย่างไร',
      en: 'What happens if the network or the HIS is down?',
    },
    a: {
      th: 'ตรวจสอบพฤติกรรมจริงของระบบก่อนนำเสนอ อย่าตอบแบบด้นสด',
      en: 'Verify the current behaviour against the running system before the pitch. Do not improvise this one.',
    },
    verify: true,
  },
  {
    q: { th: 'ขอดูเหตุผลของ AI สักเคสได้ไหม', en: 'Can we see the AI reasoning for one case?' },
    a: {
      th: 'ได้ — หน้า trace ต่อเซสชันในพอร์ทัลผู้ดูแลแสดงว่าโมเดลเห็นอะไรและกฎข้อไหนทำงานในทุกขั้นตอน',
      en: 'Yes — the per-session trace in the admin portal shows what the model saw and which rule fired at every step.',
    },
    hasDemo: 'Have the tab open, but do not show it unprompted',
  },
];
