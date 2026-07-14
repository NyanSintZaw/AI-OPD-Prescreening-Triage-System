import { useEffect, useRef } from 'react';
import { Html5Qrcode, Html5QrcodeSupportedFormats } from 'html5-qrcode';

interface QrScannerProps {
  /** Fired with the decoded text of the first successful scan. */
  onDetected: (text: string) => void;
  /** Fired if the camera can't be opened (permission denied / no device). */
  onCameraError: () => void;
}

const REGION_ID = 'kiosk-qr-region';

// Visit slips may carry a QR code or a 1D barcode — support the common ones.
const FORMATS = [
  Html5QrcodeSupportedFormats.QR_CODE,
  Html5QrcodeSupportedFormats.CODE_128,
  Html5QrcodeSupportedFormats.CODE_39,
  Html5QrcodeSupportedFormats.EAN_13,
  Html5QrcodeSupportedFormats.ITF,
  Html5QrcodeSupportedFormats.CODABAR,
];

/**
 * Camera-based Visit ID scanner. Mounts a live camera preview into a fixed
 * region and calls `onDetected` on the first decode. Cleans the camera up on
 * unmount so the LED/stream never lingers between kiosk sessions.
 */
export function QrScanner({ onDetected, onCameraError }: QrScannerProps) {
  const scannerRef = useRef<Html5Qrcode | null>(null);
  const doneRef = useRef(false);

  useEffect(() => {
    doneRef.current = false;
    let scanner: Html5Qrcode;
    try {
      scanner = new Html5Qrcode(REGION_ID, {
        formatsToSupport: FORMATS,
        verbose: false,
      });
    } catch {
      onCameraError();
      return;
    }
    scannerRef.current = scanner;

    scanner
      .start(
        { facingMode: 'environment' },
        { fps: 10, qrbox: { width: 320, height: 220 } },
        (decodedText) => {
          if (doneRef.current) return;
          doneRef.current = true;
          onDetected(decodedText);
        },
        () => {
          /* per-frame decode failures are normal — ignore */
        },
      )
      .catch(() => onCameraError());

    return () => {
      const s = scannerRef.current;
      if (s) {
        s.stop()
          .then(() => s.clear())
          .catch(() => {
            /* already stopped */
          });
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <div id={REGION_ID} />;
}
