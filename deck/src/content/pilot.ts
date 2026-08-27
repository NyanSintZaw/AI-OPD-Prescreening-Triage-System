/**
 * The pilot's success criteria, split out like `business.ts` and `prep.ts`.
 *
 * The point of this slide is that the pilot is not a demonstration. A demo
 * shows the thing works; this measures whether it was worth doing. Every metric
 * is captured on both sides of the change, which is why the table repeats
 * "Baseline / Measured" nine times rather than summarising — a hospital reading
 * it can see that nothing was chosen after the results came in.
 */
import type { Slide } from './types';

type Pilot = Extract<Slide, { layout: 'pilot' }>;

export const PILOT_TABLE: Pilot['table'] = {
  columns: ['KPI', 'Before MALI', 'During MALI'],
  rows: [
    { kpi: 'Patients screened / day', before: 'Baseline', during: 'Measured' },
    { kpi: 'Average screening time', before: 'Baseline', during: 'Measured' },
    { kpi: 'Nurse minutes / patient', before: 'Baseline', during: 'Measured' },
    { kpi: 'Waiting time', before: 'Baseline', during: 'Measured' },
    { kpi: 'Patients requiring nurse intervention', before: 'Baseline', during: 'Measured' },
    { kpi: 'Screening completion rate', before: 'Baseline', during: 'Measured' },
    { kpi: 'Patient satisfaction', before: 'Baseline', during: 'Measured' },
    { kpi: 'Nurse satisfaction', before: 'Baseline', during: 'Measured' },
    { kpi: 'Escalation / error rate', before: 'Baseline', during: 'Measured' },
  ],
};

export const PILOT_OUTCOME: Pilot['outcome'] = {
  label: 'AT THE END OF THE PILOT',
  title: 'Hospital Operational Impact Report',
  body: 'Produced from the measurements above, and the foundation for the deployment proposal.',
};
