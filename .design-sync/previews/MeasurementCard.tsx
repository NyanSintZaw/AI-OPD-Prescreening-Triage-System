import { MeasurementCard } from 'hospital-hotline-assistant-web';

const noop = () => {};

// No session id in the preview browser's localStorage, so the card never
// polls the backend — every cell below is the static first render.

export const TemperatureRequest = () => (
  <div style={{ maxWidth: 520 }}>
    <MeasurementCard vital="temp" language="th" onSubmit={noop} />
  </div>
);

export const BloodPressureChoice = () => (
  <div style={{ maxWidth: 520 }}>
    <MeasurementCard vital="sbp" language="th" onSubmit={noop} onRest={noop} />
  </div>
);

export const WeightAndHeight = () => (
  <div style={{ maxWidth: 520 }}>
    <MeasurementCard vital="weight" language="th" onSubmit={noop} />
  </div>
);

export const TemperatureWithCancel = () => (
  <div style={{ maxWidth: 520 }}>
    <MeasurementCard vital="temp" language="th" onSubmit={noop} onCancel={noop} />
  </div>
);
