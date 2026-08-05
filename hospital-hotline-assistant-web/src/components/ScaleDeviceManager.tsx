import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import type {
  BpScanDeviceOut,
  ScaleDeviceStatusOut,
  WeightScaleFetchResponse,
} from '../api/types';

type WizardStep = 'idle' | 'scanning' | 'select' | 'pairing' | 'paired' | 'pair-error';

function truncateMac(mac: string): string {
  return mac.length > 17 ? `${mac.slice(0, 8)}…${mac.slice(-4)}` : mac;
}

/** 0-4 filled bars from RSSI; null RSSI renders as unknown. */
function barsFromRssi(rssi: number | null): number {
  if (rssi == null) return 0;
  if (rssi >= -50) return 4;
  if (rssi >= -62) return 3;
  if (rssi >= -74) return 2;
  return 1;
}

function SignalBars({ rssi }: { rssi: number | null }) {
  const bars = barsFromRssi(rssi);
  return (
    <span
      className="bpdev-signal"
      title={rssi != null ? `${rssi} dBm` : undefined}
      aria-label={rssi != null ? `${rssi} dBm` : 'unknown signal'}
    >
      {[1, 2, 3, 4].map((level) => (
        <span
          key={level}
          className={`bpdev-signal-bar ${level <= bars ? 'on' : ''}`}
          style={{ height: `${4 + level * 3}px` }}
        />
      ))}
    </span>
  );
}

function ScaleIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3C7.03 3 3 7.03 3 12s4.03 9 9 9 9-4.03 9-9-4.03-9-9-9zm0 2c3.87 0 7 3.13 7 7h-4.18L16 8.83 14.59 7.4 11.4 10.6c-.13-.04-.26-.1-.4-.1a1.5 1.5 0 100 3 1.5 1.5 0 001.5-1.5h6.4A7 7 0 115 12c0-3.87 3.13-7 7-7z" />
    </svg>
  );
}

/**
 * Admin-portal manager for the kiosk's Omron HBF-222T weight scale.
 * Counterpart of BpDeviceManager: scan → select → pair wizard plus a live
 * test read against the configured scale. Reuses the bpdev-* styles.
 */
export function ScaleDeviceManager() {
  const { t } = useTranslation();

  const [status, setStatus] = useState<ScaleDeviceStatusOut | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);

  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<WeightScaleFetchResponse | null>(null);

  const [step, setStep] = useState<WizardStep>('idle');
  const [devices, setDevices] = useState<BpScanDeviceOut[]>([]);
  const [selectedMac, setSelectedMac] = useState<string | null>(null);
  const [pairError, setPairError] = useState<string | null>(null);

  useEffect(() => {
    void loadStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadStatus = async () => {
    try {
      const data = await api.getScaleDeviceStatus();
      setStatus(data);
      setStatusError(null);
    } catch (err) {
      setStatusError(err instanceof Error ? err.message : t('error'));
    }
  };

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await api.fetchWeightScale();
      setTestResult(result);
    } catch (err) {
      setTestResult({
        status: 'error',
        weight_kg: null,
        measured_at: null,
        sequence: null,
        is_recent: null,
        reading_id: null,
        message: err instanceof Error ? err.message : t('error'),
      });
    } finally {
      setTesting(false);
    }
  };

  const runScan = async () => {
    setStep('scanning');
    setSelectedMac(null);
    setPairError(null);
    try {
      const result = await api.scanScaleDevices();
      if (result.status !== 'ok') {
        setPairError(result.message ?? t('error'));
        setStep('pair-error');
        return;
      }
      setDevices(result.devices);
      // Preselect the strongest likely-Omron device (already sorted first).
      const omron = result.devices.find((d) => d.is_omron);
      if (omron) setSelectedMac(omron.mac);
      setStep('select');
    } catch (err) {
      setPairError(err instanceof Error ? err.message : t('error'));
      setStep('pair-error');
    }
  };

  const runPair = async () => {
    if (!selectedMac) return;
    setStep('pairing');
    setPairError(null);
    try {
      const result = await api.pairScaleDevice(selectedMac);
      if (result.status === 'ok') {
        setStep('paired');
        void loadStatus();
        return;
      }
      setPairError(result.message ?? t('error'));
      setStep('pair-error');
    } catch (err) {
      setPairError(err instanceof Error ? err.message : t('error'));
      setStep('pair-error');
    }
  };

  const selectedDevice = devices.find((d) => d.mac === selectedMac) ?? null;
  const testErrorKey =
    testResult && testResult.status !== 'ok'
      ? testResult.status === 'device_not_found' || testResult.status === 'timeout'
        ? 'scaledevTestNotFound'
        : testResult.status === 'busy'
          ? 'vitalsErrBusy'
          : testResult.status === 'no_records'
            ? 'scaledevNoRecords'
            : 'scaledevTestFailed'
      : null;

  return (
    <div className="bpdev-container">
      <header className="surv-header">
        <div>
          <h2 className="surv-title">{t('scaledevTitle')}</h2>
          <p className="surv-subtitle muted">{t('scaledevSubtitle')}</p>
        </div>
      </header>

      {statusError && <p className="error-text">{statusError}</p>}

      <div className="bpdev-grid">
        {/* ── Current device ─────────────────────────────────────────── */}
        <section className="bpdev-card">
          <h3 className="bpdev-card-title">{t('bpdevCurrentTitle')}</h3>

          <div className="bpdev-current">
            <span className={`bpdev-device-icon ${status?.configured ? 'ok' : ''}`}>
              <ScaleIcon />
            </span>
            <div className="bpdev-current-info">
              <span className="bpdev-model">HBF-222T</span>
              {status?.device_mac ? (
                <code className="bpdev-mac" title={status.device_mac}>
                  {truncateMac(status.device_mac)}
                </code>
              ) : (
                <span className="muted">{t('bpdevNoMac')}</span>
              )}
              <span
                className={`bpdev-chip ${status?.configured ? 'chip-ok' : 'chip-warn'}`}
              >
                {status?.configured ? t('bpdevConfigured') : t('bpdevNotConfigured')}
              </span>
              {status && (
                <span className="muted">
                  {t('scaledevMode', { mode: status.read_mode })}
                  {status.user_slot != null ? ` · ${t('scaledevSlot', { slot: status.user_slot })}` : ''}
                </span>
              )}
            </div>
          </div>

          <p className="muted bpdev-hint">{t('scaledevTestHint')}</p>
          <button
            type="button"
            className="primary-btn bpdev-test-btn"
            onClick={() => void runTest()}
            disabled={testing || !status?.configured || step === 'scanning' || step === 'pairing'}
          >
            {testing ? t('bpdevTesting') : t('scaledevTestButton')}
          </button>

          {testing && (
            <div className="vitals-progress bpdev-progress">
              <div className="vitals-progress-bar" />
            </div>
          )}

          {testResult?.status === 'ok' && (
            <div className="bpdev-test-result">
              <span className="bpdev-test-ok">✓ {t('bpdevTestOk')}</span>
              <div className="bpdev-test-values">
                <span>
                  <strong>{testResult.weight_kg}</strong> {t('vitalsUnitKg')}
                </span>
                {testResult.measured_at && (
                  <span className="muted">
                    {t('vitalsMeasuredAt', {
                      time: new Date(testResult.measured_at).toLocaleTimeString(),
                    })}
                  </span>
                )}
              </div>
            </div>
          )}
          {testErrorKey && <p className="error-text bpdev-test-error">{t(testErrorKey)}</p>}
        </section>

        {/* ── Pairing wizard ─────────────────────────────────────────── */}
        <section className="bpdev-card">
          <h3 className="bpdev-card-title">{t('scaledevPairTitle')}</h3>

          {step === 'idle' && (
            <>
              <ol className="bpdev-steps">
                <li>{t('scaledevPairStep1')}</li>
                <li>{t('scaledevPairStep2')}</li>
                <li>{t('scaledevPairStep3')}</li>
              </ol>
              <button
                type="button"
                className="primary-btn"
                onClick={() => void runScan()}
                disabled={testing}
              >
                {t('bpdevScanButton')}
              </button>
            </>
          )}

          {step === 'scanning' && (
            <div className="bpdev-center">
              <span className="bpdev-radar" aria-hidden="true" />
              <p>{t('bpdevScanning')}</p>
              <p className="muted">{t('scaledevScanningHint')}</p>
            </div>
          )}

          {step === 'select' && (
            <>
              {devices.length === 0 ? (
                <p className="muted">{t('bpdevNoDevices')}</p>
              ) : (
                <div className="bpdev-table-wrap">
                  <table className="bpdev-table">
                    <thead>
                      <tr>
                        <th>{t('bpdevColSignal')}</th>
                        <th>{t('bpdevColName')}</th>
                        <th>{t('bpdevColAddress')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {devices.map((device) => (
                        <tr
                          key={device.mac}
                          className={`bpdev-row ${device.is_omron ? 'omron' : ''} ${
                            selectedMac === device.mac ? 'selected' : ''
                          }`}
                          onClick={() => setSelectedMac(device.mac)}
                        >
                          <td>
                            <SignalBars rssi={device.rssi} />
                          </td>
                          <td>
                            <span className={device.name ? '' : 'muted'}>
                              {device.name ?? t('bpdevUnknownDevice')}
                            </span>
                            {device.is_omron && (
                              <span className="bpdev-chip chip-ok bpdev-chip-inline">
                                {t('bpdevLikelyOmron')}
                              </span>
                            )}
                          </td>
                          <td>
                            <code className="bpdev-mac">{truncateMac(device.mac)}</code>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <div className="bpdev-actions">
                <button
                  type="button"
                  className="primary-btn"
                  onClick={() => void runPair()}
                  disabled={!selectedMac}
                >
                  {selectedDevice?.name
                    ? t('bpdevPairNamed', { name: selectedDevice.name })
                    : t('bpdevPairSelected')}
                </button>
                <button type="button" className="secondary-btn" onClick={() => void runScan()}>
                  {t('bpdevRescan')}
                </button>
                <button type="button" className="text-btn" onClick={() => setStep('idle')}>
                  {t('close')}
                </button>
              </div>
            </>
          )}

          {step === 'pairing' && (
            <div className="bpdev-center">
              <span className="vitals-icon vitals-icon-pulse bpdev-pair-icon">
                <ScaleIcon />
              </span>
              <p>{t('bpdevPairing')}</p>
              <p className="muted">{t('scaledevPairingHint')}</p>
            </div>
          )}

          {step === 'paired' && (
            <div className="bpdev-center">
              <span className="bpdev-success-check">✓</span>
              <p className="bpdev-success-title">{t('scaledevPairedTitle')}</p>
              <p className="muted">
                HBF-222T · <code className="bpdev-mac">{selectedMac && truncateMac(selectedMac)}</code>
              </p>
              <p className="muted">{t('scaledevPairedHint')}</p>
              <button type="button" className="primary-btn" onClick={() => setStep('idle')}>
                {t('bpdevDone')}
              </button>
            </div>
          )}

          {step === 'pair-error' && (
            <div className="bpdev-center">
              <p className="error-text">{pairError ?? t('error')}</p>
              <p className="muted">{t('scaledevPairErrorHint')}</p>
              <div className="bpdev-actions">
                <button type="button" className="primary-btn" onClick={() => void runScan()}>
                  {t('bpdevRescan')}
                </button>
                <button type="button" className="secondary-btn" onClick={() => setStep('idle')}>
                  {t('bpdevBackToStart')}
                </button>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
