import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { AppLanguage } from '../i18n/resources';
import type { ChatAssessment } from '../hooks/useChat';

interface PatientIdPassProps {
  sessionId: string;
  language: AppLanguage;
  assessment?: ChatAssessment | null;
  variant?: 'panel' | 'compact';
}

interface PatientIdPassPopupProps {
  sessionId: string;
  language: AppLanguage;
  assessment: ChatAssessment;
  autoOpenKey: string;
  triggerVariant?: 'primary' | 'secondary';
}

interface PatientIdImageOptions {
  sessionId: string;
  language: AppLanguage;
  labels: {
    hospitalName: string;
    appName: string;
    title: string;
    subtitle: string;
    visitId: string;
    sessionId: string;
    generatedAt: string;
    severity: string;
    department: string;
    showStaff: string;
    fromSystem: string;
    noAssessment: string;
  };
  severityText?: string;
  departmentText?: string | null;
}

function DownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3a1 1 0 0 1 1 1v8.6l2.8-2.8 1.4 1.4-5.2 5.2-5.2-5.2 1.4-1.4 2.8 2.8V4a1 1 0 0 1 1-1z" />
      <path d="M5 18h14v2H5v-2z" />
    </svg>
  );
}

function GalleryIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 4h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zm0 2v8.2l3.1-3.1a1 1 0 0 1 1.4 0l2.1 2.1 3.4-4.1a1 1 0 0 1 1.6.1L19 13V6H5zm0 12h14v-1.4l-3.4-5.1-3.2 3.9a1 1 0 0 1-1.5.1l-2.1-2.1L5 17.2V18zm4-9a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3z" />
    </svg>
  );
}

function useIsLikelyPhone() {
  const [isPhone, setIsPhone] = useState(false);

  useEffect(() => {
    const query = window.matchMedia('(max-width: 767px), (pointer: coarse)');
    const update = () => {
      const userAgentPhone = /Android|iPhone|iPod|Mobile/i.test(navigator.userAgent);
      setIsPhone(query.matches || userAgentPhone);
    };

    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);

  return isPhone;
}

function shortVisitId(sessionId: string) {
  const clean = sessionId.replace(/[^a-zA-Z0-9]/g, '').toUpperCase();
  if (clean.length <= 8) return clean;
  return `MCH-${clean.slice(0, 4)}-${clean.slice(-4)}`;
}

function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
) {
  const r = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + width - r, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + r);
  ctx.lineTo(x + width, y + height - r);
  ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
  ctx.lineTo(x + r, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

function fillRoundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
  fillStyle: string | CanvasGradient,
) {
  roundRect(ctx, x, y, width, height, radius);
  ctx.fillStyle = fillStyle;
  ctx.fill();
}

function strokeRoundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
  strokeStyle: string,
  lineWidth: number,
) {
  roundRect(ctx, x, y, width, height, radius);
  ctx.strokeStyle = strokeStyle;
  ctx.lineWidth = lineWidth;
  ctx.stroke();
}

function drawWrappedText(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  maxWidth: number,
  lineHeight: number,
) {
  const words = text.split(/\s+/);
  let line = '';
  let lineY = y;

  for (const word of words) {
    const testLine = line ? `${line} ${word}` : word;
    if (ctx.measureText(testLine).width > maxWidth && line) {
      ctx.fillText(line, x, lineY);
      line = word;
      lineY += lineHeight;
    } else {
      line = testLine;
    }
  }

  if (line) {
    ctx.fillText(line, x, lineY);
  }
}

function drawLogo(ctx: CanvasRenderingContext2D, x: number, y: number) {
  ctx.save();
  ctx.shadowColor = 'rgba(0, 0, 0, 0.18)';
  ctx.shadowBlur = 24;
  ctx.shadowOffsetY = 10;
  ctx.fillStyle = '#ffffff';
  ctx.beginPath();
  ctx.arc(x, y, 72, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  const markGradient = ctx.createLinearGradient(x - 55, y - 55, x + 55, y + 55);
  markGradient.addColorStop(0, '#3ea3cb');
  markGradient.addColorStop(1, '#213253');
  ctx.fillStyle = markGradient;
  ctx.beginPath();
  ctx.arc(x, y, 56, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = '#ffffff';
  fillRoundRect(ctx, x - 10, y - 36, 20, 72, 7, '#ffffff');
  fillRoundRect(ctx, x - 36, y - 10, 72, 20, 7, '#ffffff');

  ctx.font = "700 20px 'Noto Sans Thai', system-ui, sans-serif";
  ctx.textAlign = 'center';
  ctx.fillText('MFU', x, y + 90);
}

function drawBarcode(ctx: CanvasRenderingContext2D, sessionId: string, x: number, y: number) {
  const clean = sessionId.replace(/-/g, '');
  let cursor = x;
  for (let index = 0; index < clean.length; index += 1) {
    const value = Number.parseInt(clean[index], 16);
    const width = 3 + ((Number.isNaN(value) ? index : value) % 5);
    const height = 70 + ((Number.isNaN(value) ? index : value) % 4) * 12;
    ctx.fillStyle = index % 3 === 0 ? '#213253' : '#3ea3cb';
    ctx.fillRect(cursor, y + (112 - height), width, height);
    cursor += width + 5;
    if (cursor > x + 760) break;
  }
}

async function canvasToBlob(canvas: HTMLCanvasElement) {
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) {
        resolve(blob);
      } else {
        reject(new Error('Unable to create image'));
      }
    }, 'image/png');
  });
}

async function createPatientIdImage(options: PatientIdImageOptions) {
  const { sessionId, labels, language, severityText, departmentText } = options;
  const canvas = document.createElement('canvas');
  canvas.width = 1200;
  canvas.height = 1600;

  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Canvas is not supported');

  const generatedAt = new Date().toLocaleString(language === 'th' ? 'th-TH' : 'en-US', {
    dateStyle: 'medium',
    timeStyle: 'short',
  });

  const background = ctx.createLinearGradient(0, 0, 1200, 1600);
  background.addColorStop(0, '#f7fbfd');
  background.addColorStop(0.55, '#ffffff');
  background.addColorStop(1, '#fff9eb');
  ctx.fillStyle = background;
  ctx.fillRect(0, 0, 1200, 1600);

  const header = ctx.createLinearGradient(0, 0, 1200, 460);
  header.addColorStop(0, '#213253');
  header.addColorStop(0.62, '#246587');
  header.addColorStop(1, '#3ea3cb');
  ctx.fillStyle = header;
  ctx.fillRect(0, 0, 1200, 460);

  ctx.save();
  ctx.globalAlpha = 0.24;
  ctx.fillStyle = '#ba9643';
  ctx.translate(880, -140);
  ctx.rotate(0.62);
  ctx.fillRect(0, 0, 210, 760);
  ctx.restore();

  ctx.save();
  ctx.globalAlpha = 0.16;
  ctx.strokeStyle = '#ffffff';
  ctx.lineWidth = 6;
  for (let radius = 160; radius <= 520; radius += 80) {
    ctx.beginPath();
    ctx.arc(980, 120, radius, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.restore();

  drawLogo(ctx, 160, 150);

  ctx.fillStyle = '#ffffff';
  ctx.textAlign = 'left';
  ctx.font = "700 54px 'Noto Sans Thai', 'Athiti', system-ui, sans-serif";
  drawWrappedText(ctx, labels.title, 270, 120, 750, 60);
  ctx.font = "500 30px 'Noto Sans Thai', 'Athiti', system-ui, sans-serif";
  ctx.fillStyle = 'rgba(255, 255, 255, 0.86)';
  drawWrappedText(ctx, labels.hospitalName, 270, 235, 760, 42);
  ctx.font = "700 24px 'Noto Sans Thai', 'Athiti', system-ui, sans-serif";
  ctx.fillStyle = '#f4d681';
  ctx.fillText(labels.fromSystem, 270, 340);

  ctx.save();
  ctx.shadowColor = 'rgba(33, 50, 83, 0.18)';
  ctx.shadowBlur = 34;
  ctx.shadowOffsetY = 22;
  fillRoundRect(ctx, 78, 400, 1044, 1035, 32, '#ffffff');
  ctx.restore();
  strokeRoundRect(ctx, 78, 400, 1044, 1035, 32, '#e0e7ef', 3);

  ctx.textAlign = 'center';
  ctx.fillStyle = '#705a28';
  ctx.font = "700 32px 'Noto Sans Thai', 'Athiti', system-ui, sans-serif";
  ctx.fillText(labels.visitId, 600, 510);

  ctx.fillStyle = '#213253';
  ctx.font = "800 92px 'Noto Sans Thai', 'Athiti', system-ui, sans-serif";
  ctx.fillText(shortVisitId(sessionId), 600, 625);

  ctx.fillStyle = '#5c6670';
  ctx.font = "500 26px 'Noto Sans Thai', 'Athiti', system-ui, sans-serif";
  ctx.fillText(labels.showStaff, 600, 692);

  fillRoundRect(ctx, 160, 755, 880, 170, 24, '#f2fbff');
  strokeRoundRect(ctx, 160, 755, 880, 170, 24, '#cceaf5', 2);
  drawBarcode(ctx, sessionId, 220, 790);

  const severityColor =
    severityText?.toLowerCase().includes('emergency') || severityText?.includes('ฉุกเฉิน')
      ? '#d63933'
      : severityText?.toLowerCase().includes('urgent') || severityText?.includes('เร่ง')
        ? '#ba9643'
        : '#3ea3cb';

  const detailCards = [
    {
      label: labels.severity,
      value: severityText ?? labels.noAssessment,
      color: severityColor,
    },
    {
      label: labels.department,
      value: departmentText ?? labels.noAssessment,
      color: '#213253',
    },
    {
      label: labels.generatedAt,
      value: generatedAt,
      color: '#3ea3cb',
    },
  ];

  detailCards.forEach((item, index) => {
    const y = 980 + index * 122;
    fillRoundRect(ctx, 160, y, 880, 92, 18, '#fbfcfd');
    strokeRoundRect(ctx, 160, y, 880, 92, 18, '#edf1f5', 2);
    ctx.textAlign = 'left';
    ctx.fillStyle = '#5c6670';
    ctx.font = "600 22px 'Noto Sans Thai', 'Athiti', system-ui, sans-serif";
    ctx.fillText(item.label, 205, y + 36);
    ctx.fillStyle = item.color;
    ctx.font = "700 32px 'Noto Sans Thai', 'Athiti', system-ui, sans-serif";
    drawWrappedText(ctx, item.value, 205, y + 72, 780, 36);
  });

  ctx.fillStyle = '#5c6670';
  ctx.font = "500 21px 'SFMono-Regular', Consolas, monospace";
  ctx.textAlign = 'center';
  ctx.fillText(`${labels.sessionId}: ${sessionId}`, 600, 1390);

  ctx.fillStyle = '#213253';
  ctx.font = "700 26px 'Noto Sans Thai', 'Athiti', system-ui, sans-serif";
  ctx.fillText(labels.appName, 600, 1490);
  ctx.fillStyle = '#8a95a1';
  ctx.font = "500 21px 'Noto Sans Thai', 'Athiti', system-ui, sans-serif";
  ctx.fillText(labels.subtitle, 600, 1530);

  return canvasToBlob(canvas);
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 500);
}

export function PatientIdPass({
  sessionId,
  language,
  assessment,
  variant = 'panel',
}: PatientIdPassProps) {
  const { t } = useTranslation();
  const isPhone = useIsLikelyPhone();
  const [isWorking, setIsWorking] = useState(false);
  const [statusText, setStatusText] = useState<string | null>(null);

  const visitId = useMemo(() => shortVisitId(sessionId), [sessionId]);
  const severityText = assessment?.severity
    ? t(`severity_${assessment.severity.level}`)
    : undefined;
  const departmentText = assessment?.department?.name ?? null;

  const actionLabel = isPhone ? t('patientIdSaveGallery') : t('patientIdDownload');
  const filename = `mfu-hotline-id-${visitId.toLowerCase()}.png`;

  const handleSave = async () => {
    setIsWorking(true);
    setStatusText(null);

    try {
      const blob = await createPatientIdImage({
        sessionId,
        language,
        severityText,
        departmentText,
        labels: {
          hospitalName: t('hospitalNameEn'),
          appName: t('appName'),
          title: t('patientIdImageTitle'),
          subtitle: t('patientIdImageSubtitle'),
          visitId: t('patientIdVisitId'),
          sessionId: t('patientIdSessionId'),
          generatedAt: t('patientIdGeneratedAt'),
          severity: t('severity'),
          department: t('department'),
          showStaff: t('patientIdShowStaff'),
          fromSystem: t('patientIdFromSystem'),
          noAssessment: t('patientIdPending'),
        },
      });

      const file = new File([blob], filename, { type: 'image/png' });
      const shareNavigator = navigator as Navigator & {
        canShare?: (data: ShareData) => boolean;
        share?: (data: ShareData) => Promise<void>;
      };

      if (
        isPhone &&
        typeof shareNavigator.share === 'function' &&
        typeof shareNavigator.canShare === 'function' &&
        shareNavigator.canShare({ files: [file] })
      ) {
        await shareNavigator.share({
          files: [file],
          title: t('patientIdImageTitle'),
          text: t('patientIdShareText'),
        });
        setStatusText(t('patientIdSaved'));
      } else {
        downloadBlob(blob, filename);
        setStatusText(t('patientIdDownloaded'));
      }
    } catch (error) {
      const isAbort =
        error instanceof DOMException && (error.name === 'AbortError' || error.name === 'NotAllowedError');
      if (!isAbort) {
        console.error(error);
        setStatusText(t('patientIdError'));
      }
    } finally {
      setIsWorking(false);
    }
  };

  if (variant === 'compact') {
    return (
      <div className="patient-id-compact">
        <div>
          <span className="patient-id-kicker">{t('patientIdKicker')}</span>
          <strong>{visitId}</strong>
        </div>
        <button
          type="button"
          className="secondary-btn patient-id-btn"
          onClick={() => void handleSave()}
          disabled={isWorking}
        >
          <span className="patient-id-btn-icon" aria-hidden="true">
            {isPhone ? <GalleryIcon /> : <DownloadIcon />}
          </span>
          {isWorking ? t('patientIdPreparing') : actionLabel}
        </button>
        {statusText && <span className="patient-id-status">{statusText}</span>}
      </div>
    );
  }

  return (
    <div className="patient-id-panel">
      <div className="patient-id-copy">
        <span className="patient-id-kicker">{t('patientIdKicker')}</span>
        <h3>{t('patientIdTitle')}</h3>
        <p>{t('patientIdDescription')}</p>
        <code>{visitId}</code>
      </div>
      <div className="patient-id-actions">
        <button
          type="button"
          className="primary-btn patient-id-btn"
          onClick={() => void handleSave()}
          disabled={isWorking}
        >
          <span className="patient-id-btn-icon" aria-hidden="true">
            {isPhone ? <GalleryIcon /> : <DownloadIcon />}
          </span>
          {isWorking ? t('patientIdPreparing') : actionLabel}
        </button>
        {statusText && <span className="patient-id-status">{statusText}</span>}
      </div>
    </div>
  );
}

export function PatientIdPassPopup({
  sessionId,
  language,
  assessment,
  autoOpenKey,
  triggerVariant = 'secondary',
}: PatientIdPassPopupProps) {
  const { t } = useTranslation();
  const isPhone = useIsLikelyPhone();
  const [open, setOpen] = useState(true);

  useEffect(() => {
    setOpen(true);
  }, [autoOpenKey]);

  useEffect(() => {
    if (!open) return undefined;

    const previousOverflow = document.body.style.overflow;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
      }
    };

    document.body.style.overflow = 'hidden';
    window.addEventListener('keydown', handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [open]);

  const actionLabel = isPhone ? t('patientIdSaveGallery') : t('patientIdDownload');
  const triggerClass =
    triggerVariant === 'primary'
      ? 'primary-btn patient-id-btn'
      : 'secondary-btn patient-id-btn';

  return (
    <>
      <div className="patient-id-popup-launcher">
        <button type="button" className={triggerClass} onClick={() => setOpen(true)}>
          <span className="patient-id-btn-icon" aria-hidden="true">
            {isPhone ? <GalleryIcon /> : <DownloadIcon />}
          </span>
          {actionLabel}
        </button>
      </div>

      {open && (
        <div className="patient-id-modal" role="dialog" aria-modal="true" aria-labelledby="patient-id-modal-title">
          <button
            type="button"
            className="patient-id-modal-backdrop"
            aria-label={t('close')}
            onClick={() => setOpen(false)}
          />
          <div className="patient-id-modal-card">
            <div className="patient-id-modal-header">
              <div>
                <span className="patient-id-kicker">{t('patientIdKicker')}</span>
                <h2 id="patient-id-modal-title">{t('patientIdPopupTitle')}</h2>
              </div>
              <button
                type="button"
                className="icon-btn patient-id-modal-close"
                onClick={() => setOpen(false)}
                aria-label={t('close')}
              >
                x
              </button>
            </div>
            <PatientIdPass
              sessionId={sessionId}
              language={language}
              assessment={assessment}
              variant="panel"
            />
          </div>
        </div>
      )}
    </>
  );
}
