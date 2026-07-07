import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import type {
  BloodPressureFetchResponse,
  BpDeviceStatusOut,
  BpScanDeviceOut,
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

function MonitorIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z" />
    </svg>
  );
}

/**
 * Admin-portal manager for the kiosk's Omron blood-pressure cuff.
 * Mirrors omblepy's scan → select → pair flow as a guided wizard and
 * lets staff run a live test reading against the configured device.
 */
export function BpDeviceManager() {
  const { t } = useTranslation();

  const [status, setStatus] = useState<BpDeviceStatusOut | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);

  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<BloodPressureFetchResponse | null>(null);

  const [step, setStep] = useState<WizardStep>('idle');
  const [devices, setDevices] = useState<BpScanDeviceOut[]>([]);
  const [selectedMac, setSelectedMac] = useState<string | null>(null);
  const [model, setModel] = useState<string>('hem-7280t');
  const [pairError, setPairError] = useState<string | null>(null);

  useEffect(() => {
    void loadStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadStatus = async () => {
    try {
      const data = await api.getBpDeviceStatus();
      setStatus(data);
      setStatusError(null);
      if (data.device_name) setModel(data.device_name);
    } catch (err) {
      setStatusError(err instanceof Error ? err.message : t('error'));
    }
  };

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await api.fetchBloodPressure();
      setTestResult(result);
    } catch (err) {
      setTestResult({
        status: 'error',
        systolic: null,
        diastolic: null,
        pulse_bpm: null,
        measured_at: null,
        is_recent: null,
        irregular_heartbeat: null,
        body_movement: null,
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
      const result = await api.scanBpDevices();
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
      const result = await api.pairBpDevice({ mac: selectedMac, device_name: model });
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
        ? 'bpdevTestNotFound'
        : testResult.status === 'busy'
          ? 'vitalsErrBusy'
          : testResult.status === 'no_records'
            ? 'vitalsErrNoRecords'
            : 'bpdevTestFailed'
      : null;

  return (
    <div className="bpdev-container">
      <header className="surv-header">
        <div>
          <h2 className="surv-title">{t('bpdevTitle')}</h2>
          <p className="surv-subtitle muted">{t('bpdevSubtitle')}</p>
        </div>
      </header>

      {statusError && <p className="error-text">{statusError}</p>}

      <div className="bpdev-grid">
        {/* ── Current device ─────────────────────────────────────────── */}
        <section className="bpdev-card">
          <h3 className="bpdev-card-title">{t('bpdevCurrentTitle')}</h3>

          <div className="bpdev-current">
            <span className={`bpdev-device-icon ${status?.configured ? 'ok' : ''}`}>
              <MonitorIcon />
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

          <p className="muted bpdev-hint">{t('bpdevTestHint')}</p>
          <button
            type="button"
            className="primary-btn bpdev-test-btn"
            onClick={() => void runTest()}
            disabled={testing || !status?.configured || step === 'scanning' || step === 'pairing'}
          >
            {testing ? t('bpdevTesting') : t('bpdevTestButton')}
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
                  <strong>{testResult.systolic}/{testResult.diastolic}</strong>{' '}
                  {t('vitalsUnitMmhg')}
                </span>
                <span>
                  <strong>{testResult.pulse_bpm}</strong> {t('vitalsUnitBpm')}
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
          <h3 className="bpdev-card-title">{t('bpdevPairTitle')}</h3>

          {step === 'idle' && (
            <>
              <ol className="bpdev-steps">
                <li>{t('bpdevPairStep1')}</li>
                <li>{t('bpdevPairStep2')}</li>
                <li>{t('bpdevPairStep3')}</li>
              </ol>
              <label className="bpdev-field">
                <span>{t('bpdevModelLabel')}</span>
                <select
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  className="bpdev-select"
                >
                  {(status?.supported_models ?? [model]).map((m) => (
                    <option key={m} value={m}>
                      {m.toUpperCase()}
                    </option>
                  ))}
                </select>
              </label>
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
              <p className="muted">{t('bpdevScanningHint')}</p>
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
                <MonitorIcon />
              </span>
              <p>{t('bpdevPairing')}</p>
              <p className="muted">{t('bpdevPairingHint')}</p>
            </div>
          )}

          {step === 'paired' && (
            <div className="bpdev-center">
              <span className="bpdev-success-check">✓</span>
              <p className="bpdev-success-title">{t('bpdevPairedTitle')}</p>
              <p className="muted">
                {model.toUpperCase()} · <code className="bpdev-mac">{selectedMac && truncateMac(selectedMac)}</code>
              </p>
              <p className="muted">{t('bpdevPairedHint')}</p>
              <button type="button" className="primary-btn" onClick={() => setStep('idle')}>
                {t('bpdevDone')}
              </button>
            </div>
          )}

          {step === 'pair-error' && (
            <div className="bpdev-center">
              <p className="error-text">{pairError ?? t('error')}</p>
              <p className="muted">{t('bpdevPairErrorHint')}</p>
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
