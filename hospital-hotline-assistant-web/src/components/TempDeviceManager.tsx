import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import type {
  TempDeviceStatusOut,
  TempScanDeviceOut,
  TemperatureFetchResponse,
} from '../api/types';
import { SignalBars, truncateMac } from './BpDeviceManager';

type WizardStep = 'idle' | 'scanning' | 'select' | 'pairing' | 'paired' | 'pair-error';

function ThermometerIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M15 13V5a3 3 0 0 0-6 0v8a5 5 0 1 0 6 0zm-3-9a1 1 0 0 1 1 1v8.54l.5.36a3 3 0 1 1-3 0l.5-.36V5a1 1 0 0 1 1-1z" />
      <circle cx="12" cy="17" r="2" />
    </svg>
  );
}

/**
 * Admin-portal manager for the kiosk's BLE thermometer (standard Health
 * Thermometer Service, e.g. TAIDOC TD1242). Same scan → select → connect
 * wizard as the BP cuff, minus pairing keys — connecting just verifies the
 * device and saves its address.
 */
export function TempDeviceManager() {
  const { t } = useTranslation();

  const [status, setStatus] = useState<TempDeviceStatusOut | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);

  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TemperatureFetchResponse | null>(null);

  const [step, setStep] = useState<WizardStep>('idle');
  const [devices, setDevices] = useState<TempScanDeviceOut[]>([]);
  const [selectedMac, setSelectedMac] = useState<string | null>(null);
  const [pairError, setPairError] = useState<string | null>(null);

  useEffect(() => {
    void loadStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadStatus = async () => {
    try {
      const data = await api.getTempDeviceStatus();
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
      const result = await api.fetchTemperature();
      setTestResult(result);
    } catch (err) {
      setTestResult({
        status: 'error',
        temperature_c: null,
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
      const result = await api.scanTempDevices();
      if (result.status !== 'ok') {
        setPairError(result.message ?? t('error'));
        setStep('pair-error');
        return;
      }
      setDevices(result.devices);
      // Preselect the strongest likely thermometer (already sorted first).
      const thermo = result.devices.find((d) => d.is_thermometer);
      if (thermo) setSelectedMac(thermo.mac);
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
      const result = await api.pairTempDevice({ mac: selectedMac });
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
        ? 'tempdevTestNotFound'
        : testResult.status === 'timeout'
          ? 'tempdevTestTimeout'
          : testResult.status === 'busy'
            ? 'vitalsErrBusy'
            : 'tempdevTestFailed'
      : null;

  return (
    <div className="bpdev-container">
      <header className="surv-header">
        <div>
          <h2 className="surv-title">{t('tempdevTitle')}</h2>
          <p className="surv-subtitle muted">{t('tempdevSubtitle')}</p>
        </div>
      </header>

      {statusError && <p className="error-text">{statusError}</p>}

      <div className="bpdev-grid">
        {/* ── Current device ─────────────────────────────────────────── */}
        <section className="bpdev-card">
          <h3 className="bpdev-card-title">{t('bpdevCurrentTitle')}</h3>

          <div className="bpdev-current">
            <span className={`bpdev-device-icon ${status?.configured ? 'ok' : ''}`}>
              <ThermometerIcon />
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

          <p className="muted bpdev-hint">{t('tempdevTestHint')}</p>
          <button
            type="button"
            className="primary-btn bpdev-test-btn"
            onClick={() => void runTest()}
            disabled={testing || !status?.configured || step === 'scanning' || step === 'pairing'}
          >
            {testing ? t('tempdevTesting') : t('bpdevTestButton')}
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
                  <strong>{testResult.temperature_c}</strong> °C
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

        {/* ── Connect wizard ─────────────────────────────────────────── */}
        <section className="bpdev-card">
          <h3 className="bpdev-card-title">{t('tempdevPairTitle')}</h3>

          {step === 'idle' && (
            <>
              <ol className="bpdev-steps">
                <li>{t('tempdevPairStep1')}</li>
                <li>{t('tempdevPairStep2')}</li>
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
              <p className="muted">{t('tempdevScanningHint')}</p>
            </div>
          )}

          {step === 'select' && (
            <>
              {devices.length === 0 ? (
                <p className="muted">{t('tempdevNoDevices')}</p>
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
                          className={`bpdev-row ${device.is_thermometer ? 'omron' : ''} ${
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
                            {device.is_thermometer && (
                              <span className="bpdev-chip chip-ok bpdev-chip-inline">
                                {t('tempdevLikelyThermometer')}
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
                    ? t('tempdevConnectNamed', { name: selectedDevice.name })
                    : t('tempdevConnectSelected')}
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
                <ThermometerIcon />
              </span>
              <p>{t('tempdevPairing')}</p>
              <p className="muted">{t('tempdevPairingHint')}</p>
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
              <p className="muted">{t('tempdevPairedHint')}</p>
              <button type="button" className="primary-btn" onClick={() => setStep('idle')}>
                {t('bpdevDone')}
              </button>
            </div>
          )}

          {step === 'pair-error' && (
            <div className="bpdev-center">
              <p className="error-text">{pairError ?? t('error')}</p>
              <p className="muted">{t('tempdevPairErrorHint')}</p>
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
