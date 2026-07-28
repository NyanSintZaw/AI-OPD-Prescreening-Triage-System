import { KioskFrame, Stepper, AiOrb } from 'hospital-hotline-assistant-web';

/* KioskFrame renders .kiosk-root (position:fixed inset:0 — the full booth
 * canvas). The transform makes this wrapper the containing block for that
 * fixed element, so the frame fills a booth-sized tile instead of escaping
 * the preview cell. */
const Booth = ({ children, width = 860, height = 640, zoom = 1 }: any) => (
  // Sized to fit the default 900x700 capture viewport — wider booths clip
  // the topbar's clock/language controls out of the shot. Cells whose topbar
  // needs full kiosk width (brand + stepper + clock) render at 1280 and
  // zoom down to fit.
  <div style={{ position: 'relative', width, height, zoom, transform: 'translateZ(0)', overflow: 'hidden' }}>
    {children}
  </div>
);

/** Mid-session chrome: stepper centered, Exit pill, language toggle hidden
 *  (session language is pinned) — mirrors KioskSession's composition. */
export const SessionGreeting = () => (
  <Booth width={1280} height={860} zoom={0.66}>
    <KioskFrame
      language="th"
      onLanguageChange={() => {}}
      onExit={() => {}}
      hideLanguage
      center={<Stepper current={1} />}
    >
      <div className="k-hello">
        <AiOrb state="idle" size={124} />
        <h2 className="k-hello-name">สวัสดีคุณ สมชาย ใจดี</h2>
        <p className="k-hello-lead">เรามาคุยเรื่องอาการของคุณกันค่ะ</p>
      </div>
    </KioskFrame>
  </Booth>
);

/** Attract/home chrome: brand lockup + clock + TH/EN toggle, no stepper —
 *  mirrors KioskHome's composition. */
export const HomeWelcome = () => (
  <Booth>
    <KioskFrame language="th" onLanguageChange={() => {}}>
      <div className="k-hello">
        <h2 className="k-hello-name">ยินดีต้อนรับ</h2>
        <p className="k-hello-lead">
          บอกอาการของคุณกับผู้ช่วย AI แล้วระบบจะแนะนำแผนกที่เหมาะสมให้คุณ
        </p>
      </div>
    </KioskFrame>
  </Booth>
);
