import { LanguageSwitcher } from 'hospital-hotline-assistant-web';

/* 'header' = MFU round TH/EN circles in the white header band (the variant
 * the app actually uses — Layout.tsx, LoginPage.tsx). */
export const HeaderThai = () => (
  <div style={{ background: '#ffffff', padding: 20, display: 'inline-block' }}>
    <LanguageSwitcher variant="header" language="th" onChange={() => {}} />
  </div>
);

export const HeaderEnglish = () => (
  <div style={{ background: '#ffffff', padding: 20, display: 'inline-block' }}>
    <LanguageSwitcher variant="header" language="en" onChange={() => {}} />
  </div>
);

/* 'nav' variant is white-on-transparent — invisible on a white canvas
 * (why the generic check rendered blank). Shown on the gold nav band it
 * was styled for. */
export const NavOnGoldBand = () => (
  <div style={{ background: 'var(--mch-gold, #ba9643)', padding: '14px 20px', display: 'inline-block' }}>
    <LanguageSwitcher variant="nav" language="th" onChange={() => {}} />
  </div>
);
