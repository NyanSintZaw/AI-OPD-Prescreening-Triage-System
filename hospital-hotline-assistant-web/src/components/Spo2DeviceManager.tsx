import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import type {
  Spo2DeviceStatusOut,
  Spo2FetchResponse,
  Spo2ScanDeviceOut,
} from '../api/types';
import { SignalBars, truncateMac } from './BpDeviceManager';

type WizardStep = 'idle' | 'scanning' | 'select' | 'pairing' | 'paired' | 'pair-error';

function OximeterIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      {/* Fingertip clip with a pulse trace */}
      <path d="M7 4a3 3 0 0 0-3 3v10a3 3 0 0 0 3 3h10a3 3 0 0 0 3-3V7a3 3 0 0 0-3-3H7zm0 2h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1z" />
      <path d="M6.5 13.2h2.6l1.1-2.6 1.6 4 1.3-2.4 .8 1h3.6v-1.5h-2.8l-1.5-1.9-1.2 2.2-1.7-4.3-1.9 4.3H6.5z" />
    </svg>
  );
}

/**
 * Admin-portal manager for the kiosk's fingertip pulse oximeter (Rossmax
 * SB210, advertises as RM_SPO2). Same scan → select → connect wizard as the
 * thermometer — connecting verifies the device streams the SB210 data
 * characteristic and saves its address.
 */
export function Spo2DeviceManager() {
  const { t } = useTranslation();

  const [status, setStatus] = useState<Spo2DeviceStatusOut | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);

  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<Spo2FetchResponse | null>(null);

  const [step, setStep] = useState<WizardStep>('idle');
  const [devices, setDevices] = useState<Spo2ScanDeviceOut[]>([]);
  const [selectedMac, setSelectedMac] = useState<string | null>(null);
  const [pairError, setPairError] = useState<string | null>(null);

  useEffect(() => {
    void loadStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadStatus = async () => {
    try {
      const data = await api.getSpo2DeviceStatus();
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
      const result = await api.fetchSpo2();
      setTestResult(result);
    } catch (err) {
      setTestResult({
        status: 'error',
        spo2: null,
        pulse_bpm: null,
        measured_at: null,
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
      const result = await api.scanSpo2Devices();
      if (result.status !== 'ok') {
        setPairError(result.message ?? t('error'));
        setStep('pair-error');
        return;
      }
      setDevices(result.devices);
      // Preselect the strongest likely oximeter (already sorted first).
      const oximeter = result.devices.find((d) => d.is_oximeter);
      if (oximeter) setSelectedMac(oximeter.mac);
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
      const scanName = devices.find((d) => d.mac === selectedMac)?.name ?? null;
      const result = await api.pairSpo2Device({ mac: selectedMac, name: scanName });
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
      ? testResult.status === 'device_not_found'
        ? 'spo2devTestNotFound'
        : testResult.status === 'timeout'
          ? 'spo2devTestTimeout'
          : testResult.status === 'unstable'
            ? 'spo2devTestUnstable'
            : testResult.status === 'busy'
              ? 'vitalsErrBusy'
              : 'spo2devTestFailed'
      : null;

  return (
    <div className="bpdev-container">
      <header className="surv-header">
        <div>
          <h2 className="surv-title">{t('spo2devTitle')}</h2>
          <p className="surv-subtitle muted">{t('spo2devSubtitle')}</p>
        </div>
      </header>

      {statusError && <p className="error-text">{statusError}</p>}

      <div className="bpdev-grid">
        {/* ── Current device ─────────────────────────────────────────── */}
        <section className="bpdev-card">
          <h3 className="bpdev-card-title">{t('bpdevCurrentTitle')}</h3>

          <div className="bpdev-current">
            <span className={`bpdev-device-icon ${status?.configured ? 'ok' : ''}`}>
              <OximeterIcon />
            </span>
            <div className="bpdev-current-info">
              <span className="bpdev-model">
                {status ? status.device_name.toUpperCase() : '—'}
              </span>
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
            </div>
          </div>

          <p className="muted bpdev-hint">{t('spo2devTestHint')}</p>
          <button
            type="button"
            className="primary-btn bpdev-test-btn"
            onClick={() => void runTest()}
            disabled={testing || !status?.configured || step === 'scanning' || step === 'pairing'}
          >
            {testing ? t('spo2devTesting') : t('bpdevTestButton')}
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
                  SpO₂ <strong>{testResult.spo2}</strong>%
                </span>
                {testResult.pulse_bpm != null && (
                  <span>
                    <strong>{testResult.pulse_bpm}</strong> bpm
                  </span>
                )}
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

        {/* ── Connect wizard ─────────────────────────────────────────── */}
        <section className="bpdev-card">
          <h3 className="bpdev-card-title">{t('spo2devPairTitle')}</h3>

          {step === 'idle' && (
            <>
              <ol className="bpdev-steps">
                <li>{t('spo2devPairStep1')}</li>
                <li>{t('spo2devPairStep2')}</li>
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
              <p className="muted">{t('spo2devScanningHint')}</p>
            </div>
          )}

          {step === 'select' && (
            <>
              {devices.length === 0 ? (
                <p className="muted">{t('spo2devNoDevices')}</p>
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
                          className={`bpdev-row ${device.is_oximeter ? 'omron' : ''} ${
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
                            {device.is_oximeter && (
                              <span className="bpdev-chip chip-ok bpdev-chip-inline">
                                {t('spo2devLikelyOximeter')}
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
                    ? t('spo2devConnectNamed', { name: selectedDevice.name })
                    : t('spo2devConnectSelected')}
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
                <OximeterIcon />
              </span>
              <p>{t('spo2devPairing')}</p>
              <p className="muted">{t('spo2devPairingHint')}</p>
            </div>
          )}

          {step === 'paired' && (
            <div className="bpdev-center">
              <span className="bpdev-success-check">✓</span>
              <p className="bpdev-success-title">{t('bpdevPairedTitle')}</p>
              <p className="muted">
                {(selectedDevice?.name ?? status?.device_name ?? '').toUpperCase()} ·{' '}
                <code className="bpdev-mac">{selectedMac && truncateMac(selectedMac)}</code>
              </p>
              <p className="muted">{t('spo2devPairedHint')}</p>
              <button type="button" className="primary-btn" onClick={() => setStep('idle')}>
                {t('bpdevDone')}
              </button>
            </div>
          )}

          {step === 'pair-error' && (
            <div className="bpdev-center">
              <p className="error-text">{pairError ?? t('error')}</p>
              <p className="muted">{t('spo2devPairErrorHint')}</p>
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
