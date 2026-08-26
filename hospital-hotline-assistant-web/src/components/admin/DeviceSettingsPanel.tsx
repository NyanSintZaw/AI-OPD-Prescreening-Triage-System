/**
 * Admin → Device Settings.
 *
 * The three instruments used to be stacked on one page, so reaching the pulse
 * oximeter meant scrolling past two pairing wizards that had nothing to do
 * with it — and each printed its own heading on the way, under a page head
 * that had already said "Device Settings". One tab per instrument instead:
 * you are always configuring exactly one device, which is what the work
 * actually is.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { BpDeviceManager } from '../BpDeviceManager';
import { TempDeviceManager } from '../TempDeviceManager';
import { Spo2DeviceManager } from '../Spo2DeviceManager';

const DEVICES = ['bp', 'temp', 'spo2'] as const;
type Device = (typeof DEVICES)[number];

export function DeviceSettingsPanel() {
  const { t } = useTranslation();
  const [device, setDevice] = useState<Device>('bp');

  return (
    <div className="device-settings">
      <div className="tabs" role="tablist">
        {DEVICES.map((id) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={device === id}
            className={`tab ${device === id ? 'active' : ''}`}
            onClick={() => setDevice(id)}
          >
            {t(`devTab_${id}`)}
          </button>
        ))}
      </div>

      {/* Unmounted, not hidden: each manager polls its own device's status,
          and three pollers for two instruments nobody is looking at is a
          Bluetooth scan the booth never asked for. */}
      {device === 'bp' && <BpDeviceManager />}
      {device === 'temp' && <TempDeviceManager />}
      {device === 'spo2' && <Spo2DeviceManager />}
    </div>
  );
}
