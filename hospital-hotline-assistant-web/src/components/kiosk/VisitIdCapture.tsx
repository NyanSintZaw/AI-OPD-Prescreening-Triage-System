import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AnimatePresence, motion } from 'framer-motion';
import { ArrowRight, Backspace, Camera, Keyboard, Microphone, Scan } from '@phosphor-icons/react';
import type { AppLanguage } from '../../i18n/resources';
import { useVoiceVisitId } from '../../hooks/useVoiceVisitId';
import { QrScanner } from './QrScanner';

type Tab = 'type' | 'scan' | 'voice';

interface VisitIdCaptureProps {
  language: AppLanguage;
  /** Parent validates the ID against the HIS (via api.linkVisit). */
  onSubmit: (visitId: string) => void;
  onSkip: () => void;
  /** True while the parent is linking the visit. */
  linking: boolean;
  /** True when the last submitted ID wasn't found in the HIS. */
  notFound: boolean;
  /** True when the last link attempt failed to reach the HIS (network/server error). */
  linkError: boolean;
}

// The HIS visit_id is an 18-digit numeric string (confirmed from
// hospital-his-mock/sample_visits.csv, e.g. "990000000000000001").
const VISIT_ID_LENGTH = 18;
const VISIT_ID_RE = /^\d{18}$/;

/** Chunk the entered ID into groups of 4 for readable display. */
function digitGroups(value: string): string[] {
  const groups: string[] = [];
  for (let i = 0; i < value.length; i += 4) {
    groups.push(value.slice(i, i + 4));
  }
  return groups;
}

/** Shrink the digit display as the value grows so all 18 digits stay visible. */
function digitDisplayFontSize(len: number): string {
  if (len > 14) return 'clamp(18px, 2.4vw, 28px)';
  if (len > 8) return 'clamp(22px, 2.9vw, 34px)';
  return 'clamp(28px, 3.6vw, 44px)';
}

/**
 * Visit ID entry — four input paths funnelling into one value:
 * on-screen keypad, hardware HID/keyboard-wedge scanner (hidden input,
 * always listening), on-screen camera QR/barcode, and voice (STT → digits).
 */
export function VisitIdCapture({
  language,
  onSubmit,
  onSkip,
  linking,
  notFound,
  linkError,
}: VisitIdCaptureProps) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>('type');
  const [visitId, setVisitId] = useState('');
  const [cameraOn, setCameraOn] = useState(false);
  const [cameraError, setCameraError] = useState(false);
  const [formatError, setFormatError] = useState(false);
  const wedgeRef = useRef<HTMLInputElement>(null);
  const voice = useVoiceVisitId(language);

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
    setVisitId((v) => (v + d).slice(0, VISIT_ID_LENGTH));
    refocusWedge();
  };
  const backspace = () => {
    setFormatError(false);
    setVisitId((v) => v.slice(0, -1));
    refocusWedge();
  };
  const clear = () => {
    setFormatError(false);
    setVisitId('');
    refocusWedge();
  };

  const submit = (value: string) => {
    const trimmed = value.replace(/\s+/g, '').trim();
    if (!trimmed) return;
    if (!VISIT_ID_RE.test(trimmed)) {
      setFormatError(true);
      return;
    }
    setFormatError(false);
    onSubmit(trimmed);
  };

  const handleCameraDetect = (text: string) => {
    const digits = text.replace(/\D+/g, '') || text.trim();
    setCameraOn(false);
    setVisitId(digits);
    submit(digits);
  };

  const handleVoiceStop = async () => {
    const digits = await voice.stop();
    if (digits) setVisitId(digits);
  };

  const keypad = ['1', '2', '3', '4', '5', '6', '7', '8', '9'];
  const groups = digitGroups(visitId);

  return (
    <div className="k-visit">
      <div className="k-visit-head">
        <h2>{t('kioskVisitTitle')}</h2>
        <p>{t('kioskVisitSubtitle')}</p>
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
            <Keyboard size={22} weight="duotone" aria-hidden="true" /> {t('kioskVisitTabType')}
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
            <Scan size={22} weight="duotone" aria-hidden="true" /> {t('kioskVisitTabScan')}
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
            <Microphone size={22} weight="duotone" aria-hidden="true" /> {t('kioskVisitTabVoice')}
          </button>
        </div>

        <div className="k-visit-ctrl">
          {/* Current value (shared across all methods) — font shrinks as the
              value grows so the full 18-digit ID always stays visible. */}
          <div
            className={`k-display ${visitId ? '' : 'placeholder'}`}
            style={visitId ? { fontSize: digitDisplayFontSize(visitId.length) } : undefined}
          >
            {visitId ? (
              <>
                {groups.map((g, i) => (
                  <span key={i} className="k-digit-group">
                    {g}
                  </span>
                ))}
                <span className="k-caret" aria-hidden="true" />
              </>
            ) : (
              t('kioskVisitPlaceholder')
            )}
          </div>

          {formatError && <p className="k-error">{t('kioskVisitInvalidFormat')}</p>}
          {!formatError && notFound && !linking && <p className="k-error">{t('kioskVisitNotFound')}</p>}
          {!formatError && linkError && !linking && <p className="k-error">{t('kioskVisitLinkError')}</p>}

          {/* Hidden wedge-scanner sink — always mounted so hardware scans work. */}
          <input
            ref={wedgeRef}
            className="kiosk-hidden-input"
            value={visitId}
            inputMode="none"
            aria-hidden="true"
            tabIndex={-1}
            onChange={(e) => {
              setFormatError(false);
              setVisitId(e.target.value.replace(/\D+/g, '').slice(0, VISIT_ID_LENGTH));
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submit(visitId);
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
                  {t('kioskVisitKeypadClear')}
                </button>
                <button type="button" className="k-key" onClick={() => append('0')}>
                  0
                </button>
                <button
                  type="button"
                  className="k-key util"
                  onClick={backspace}
                  aria-label={t('kioskVisitKeypadBackspace')}
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
                      {t('kioskVisitScanCameraStop')}
                    </button>
                  </>
                ) : (
                  <>
                    <Scan size={54} weight="duotone" color="var(--k-primary)" aria-hidden="true" />
                    <p className="k-method-hint">{t('kioskVisitScanHint')}</p>
                    <button
                      type="button"
                      className="k-btn primary"
                      onClick={() => {
                        setCameraError(false);
                        setCameraOn(true);
                      }}
                    >
                      <Camera size={22} weight="bold" aria-hidden="true" /> {t('kioskVisitScanCamera')}
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
                  aria-label={t('kioskVisitTabVoice')}
                >
                  <Microphone size={46} weight="duotone" aria-hidden="true" />
                </button>
                <p className="k-method-hint">
                  {voice.state === 'recording'
                    ? t('kioskVisitVoiceListening')
                    : voice.state === 'processing'
                      ? t('kioskVisitVoiceProcessing')
                      : t('kioskVisitVoiceHint')}
                </p>
                {voice.error && voice.state === 'idle' && (
                  <p className="k-error">
                    {voice.error === 'stt' ? t('kioskVisitVoiceSttError') : t('kioskVisitVoiceMicError')}
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
            onClick={() => submit(visitId)}
            disabled={linking || !visitId}
          >
            {linking ? (
              <span
                className="k-spinner"
                style={{ width: 26, height: 26, borderWidth: 3 }}
                aria-label={t('kioskVisitLinking')}
              />
            ) : (
              <>
                {t('kioskVisitConfirm')} <ArrowRight size={26} weight="bold" aria-hidden="true" />
              </>
            )}
          </button>
          <button type="button" className="k-textlink" onClick={onSkip} disabled={linking}>
            {t('kioskVisitSkip')}
          </button>
        </div>
      </div>
    </div>
  );
}
