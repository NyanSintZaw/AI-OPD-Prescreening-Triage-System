import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AnimatePresence, motion } from 'framer-motion';
import { ArrowRight, Backspace, Camera, Keyboard, Microphone, Scan } from '@phosphor-icons/react';
import type { AppLanguage } from '../../i18n/resources';
import { useVoiceHn } from '../../hooks/useVoiceHn';
import { QrScanner } from './QrScanner';

type Tab = 'type' | 'scan' | 'voice';

interface HnCaptureProps {
  language: AppLanguage;
  /** Parent validates the HN against the HIS (via api.linkPatient). */
  onSubmit: (hn: string) => void;
  onSkip: () => void;
  /** True while the parent is linking the patient. */
  linking: boolean;
  /** True when the last submitted HN wasn't found in the HIS. */
  notFound: boolean;
  /** True when the last link attempt failed to reach the HIS (network/server error). */
  linkError: boolean;
  /** True when the patient rejected the spoken name confirmation — show a
   *  "that wasn't you, please re-enter your HN" hint. */
  identityRejected?: boolean;
}

// The HN (hospital number) is an 8-digit numeric string (Data Requirements
// V1 sample "09900001"; hospital-his-mock/sample_patients.csv).
const HN_LENGTH = 8;
const HN_RE = /^\d{8}$/;

/** Chunk the entered ID into groups of 4 for readable display. */
function digitGroups(value: string): string[] {
  const groups: string[] = [];
  for (let i = 0; i < value.length; i += 4) {
    groups.push(value.slice(i, i + 4));
  }
  return groups;
}

// 8 digits fit at full size — no shrink ladder needed since the VN days.

/**
 * HN entry — four input paths funnelling into one value:
 * on-screen keypad, hardware HID/keyboard-wedge scanner (hidden input,
 * always listening), on-screen camera QR/barcode (the hospital card), and
 * voice (STT → digits).
 */
export function HnCapture({
  language,
  onSubmit,
  onSkip,
  linking,
  notFound,
  linkError,
  identityRejected = false,
}: HnCaptureProps) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>('type');
  const [hn, setHn] = useState('');
  const [cameraOn, setCameraOn] = useState(false);
  const [cameraError, setCameraError] = useState(false);
  const [formatError, setFormatError] = useState(false);
  const wedgeRef = useRef<HTMLInputElement>(null);
  const voice = useVoiceHn(language);

  // Keep the invisible wedge input focused so a hardware scanner's keystrokes
  // (rapid digits terminated by Enter) are always captured, whatever tab is up.
  const refocusWedge = () => {
    if (!cameraOn && voice.state === 'idle') wedgeRef.current?.focus();
  };
  useEffect(() => {
    refocusWedge();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, cameraOn, voice.state]);

  const append = (d: string) => {
    setFormatError(false);
    setHn((v) => (v + d).slice(0, HN_LENGTH));
    refocusWedge();
  };
  const backspace = () => {
    setFormatError(false);
    setHn((v) => v.slice(0, -1));
    refocusWedge();
  };
  const clear = () => {
    setFormatError(false);
    setHn('');
    refocusWedge();
  };

  const submit = (value: string) => {
    const trimmed = value.replace(/\s+/g, '').trim();
    if (!trimmed) return;
    if (!HN_RE.test(trimmed)) {
      setFormatError(true);
      return;
    }
    setFormatError(false);
    onSubmit(trimmed);
  };

  const handleCameraDetect = (text: string) => {
    const digits = text.replace(/\D+/g, '') || text.trim();
    setCameraOn(false);
    setHn(digits);
    submit(digits);
  };

  const handleVoiceStop = async () => {
    const digits = await voice.stop();
    if (digits) setHn(digits);
  };

  const keypad = ['1', '2', '3', '4', '5', '6', '7', '8', '9'];
  const groups = digitGroups(hn);

  return (
    <div className="k-visit">
      <div className="k-visit-head">
        <h2>{t('kioskHnTitle')}</h2>
        <p>{t('kioskHnSubtitle')}</p>
      </div>

      <div className="k-card k-visit-card">
        {/* Method segmented control */}
        <div className="k-segmented k-visit-seg" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'type'}
            className={tab === 'type' ? 'active' : ''}
            onClick={() => {
              setTab('type');
              setCameraOn(false);
              setFormatError(false);
            }}
          >
            <Keyboard size={22} weight="duotone" aria-hidden="true" /> {t('kioskHnTabType')}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'scan'}
            className={tab === 'scan' ? 'active' : ''}
            onClick={() => {
              setTab('scan');
              setFormatError(false);
            }}
          >
            <Scan size={22} weight="duotone" aria-hidden="true" /> {t('kioskHnTabScan')}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'voice'}
            className={tab === 'voice' ? 'active' : ''}
            onClick={() => {
              setTab('voice');
              setCameraOn(false);
              setFormatError(false);
            }}
          >
            <Microphone size={22} weight="duotone" aria-hidden="true" /> {t('kioskHnTabVoice')}
          </button>
        </div>

        <div className="k-visit-ctrl">
          {/* Current value (shared across all methods). */}
          <div className={`k-display ${hn ? '' : 'placeholder'}`}>
            {hn ? (
              <>
                {groups.map((g, i) => (
                  <span key={i} className="k-digit-group">
                    {g}
                  </span>
                ))}
                <span className="k-caret" aria-hidden="true" />
              </>
            ) : (
              t('kioskHnPlaceholder')
            )}
          </div>

          {formatError && <p className="k-error">{t('kioskHnInvalidFormat')}</p>}
          {!formatError && notFound && !linking && <p className="k-error">{t('kioskHnNotFound')}</p>}
          {!formatError && linkError && !linking && <p className="k-error">{t('kioskHnLinkError')}</p>}
          {!formatError && identityRejected && !notFound && !linkError && !linking && (
            <p className="k-error">{t('kioskHnWrongName')}</p>
          )}

          {/* Hidden wedge-scanner sink — always mounted so hardware scans work. */}
          <input
            ref={wedgeRef}
            className="kiosk-hidden-input"
            value={hn}
            inputMode="none"
            aria-hidden="true"
            tabIndex={-1}
            onChange={(e) => {
              setFormatError(false);
              setHn(e.target.value.replace(/\D+/g, '').slice(0, HN_LENGTH));
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submit(hn);
            }}
          />
        </div>

        {/* Method-specific area */}
        <div className="k-visit-method" style={{ width: '100%' }}>
          <AnimatePresence mode="wait">
            {tab === 'type' && (
              <motion.div
                key="type"
                className="k-keypad"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.2 }}
              >
                {keypad.map((k) => (
                  <button key={k} type="button" className="k-key" onClick={() => append(k)}>
                    {k}
                  </button>
                ))}
                <button type="button" className="k-key util" onClick={clear}>
                  {t('kioskHnKeypadClear')}
                </button>
                <button type="button" className="k-key" onClick={() => append('0')}>
                  0
                </button>
                <button
                  type="button"
                  className="k-key util"
                  onClick={backspace}
                  aria-label={t('kioskHnKeypadBackspace')}
                >
                  <Backspace size={24} weight="bold" aria-hidden="true" />
                </button>
              </motion.div>
            )}

            {tab === 'scan' && (
              <motion.div
                key="scan"
                className="k-method-panel"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.2 }}
              >
                {cameraOn ? (
                  <>
                    <QrScanner
                      onDetected={handleCameraDetect}
                      onCameraError={() => {
                        setCameraError(true);
                        setCameraOn(false);
                      }}
                    />
                    <button type="button" className="k-btn secondary" onClick={() => setCameraOn(false)}>
                      {t('kioskHnScanCameraStop')}
                    </button>
                  </>
                ) : (
                  <>
                    <Scan size={54} weight="duotone" color="var(--k-primary)" aria-hidden="true" />
                    <p className="k-method-hint">{t('kioskHnScanHint')}</p>
                    <button
                      type="button"
                      className="k-btn primary"
                      onClick={() => {
                        setCameraError(false);
                        setCameraOn(true);
                      }}
                    >
                      <Camera size={22} weight="bold" aria-hidden="true" /> {t('kioskHnScanCamera')}
                    </button>
                    {cameraError && <p className="k-error">{t('kioskCameraDenied')}</p>}
                  </>
                )}
              </motion.div>
            )}

            {tab === 'voice' && (
              <motion.div
                key="voice"
                className="k-method-panel"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.2 }}
              >
                <button
                  type="button"
                  className={`k-mic-btn ${voice.state === 'recording' ? 'recording' : ''}`}
                  onClick={() => {
                    if (voice.state === 'idle') void voice.start();
                    else if (voice.state === 'recording') void handleVoiceStop();
                  }}
                  disabled={voice.state === 'processing'}
                  aria-label={t('kioskHnTabVoice')}
                >
                  <Microphone size={46} weight="duotone" aria-hidden="true" />
                </button>
                <p className="k-method-hint">
                  {voice.state === 'recording'
                    ? t('kioskHnVoiceListening')
                    : voice.state === 'processing'
                      ? t('kioskHnVoiceProcessing')
                      : t('kioskHnVoiceHint')}
                </p>
                {voice.error && voice.state === 'idle' && (
                  <p className="k-error">
                    {voice.error === 'stt' ? t('kioskHnVoiceSttError') : t('kioskHnVoiceMicError')}
                  </p>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* Footer: quiet skip link + the single primary Confirm */}
        <div className="k-visit-foot k-visit-footgrid">
          <button
            type="button"
            className="k-btn primary xl"
            style={{ width: '100%', maxWidth: 460 }}
            onClick={() => submit(hn)}
            disabled={linking || !hn}
          >
            {linking ? (
              <span
                className="k-spinner"
                style={{ width: 26, height: 26, borderWidth: 3 }}
                aria-label={t('kioskHnLinking')}
              />
            ) : (
              <>
                {t('kioskHnConfirm')} <ArrowRight size={26} weight="bold" aria-hidden="true" />
              </>
            )}
          </button>
          <button type="button" className="k-textlink" onClick={onSkip} disabled={linking}>
            {t('kioskHnSkip')}
          </button>
        </div>
      </div>
    </div>
  );
}
