import { useMemo, useRef, useState } from 'react';
import type { VoiceCallState } from '../hooks/useVoiceCall';
import { VrmAvatar } from '../components/kiosk/VrmAvatar';
import '../styles/kiosk.css';

const STATES: Array<VoiceCallState | 'idle'> = ['idle', 'listening', 'thinking', 'speaking'];

/**
 * Dev-only harness at /kiosk/avatar-dev: renders the kiosk avatar large
 * with buttons to force each conversation state and a synthetic speech
 * envelope while "speaking" — lets avatar poses and lip sync be tuned
 * (and screenshot-tested) without walking a full kiosk session. Not
 * linked from any patient-facing screen.
 */
export function AvatarDevPage() {
  // ?state=listening preselects a state — used by headless screenshot runs.
  const initial = new URLSearchParams(window.location.search).get('state');
  const [state, setState] = useState<VoiceCallState | 'idle'>(
    STATES.includes(initial as VoiceCallState | 'idle') ? (initial as VoiceCallState | 'idle') : 'idle',
  );
  const stateRef = useRef(state);
  stateRef.current = state;

  // Syllable-ish fake loudness so lip sync is visible without real TTS.
  const getLevel = useMemo(() => {
    return () => {
      if (stateRef.current !== 'speaking') return 0;
      const t = performance.now() / 1000;
      const syllables = Math.max(0, Math.sin(t * 6.2)) * 0.55 + Math.max(0, Math.sin(t * 13.7)) * 0.35;
      const pauses = Math.sin(t * 0.8) > -0.4 ? 1 : 0.05;
      return Math.min(1, syllables * pauses);
    };
  }, []);

  // Fake spectral features: the centroid sweeps slowly through 0..1 so
  // every vowel mouth (う→お→あ→え→い) shows in sequence while "speaking".
  const getFeatures = useMemo(() => {
    return () => {
      const level = getLevel();
      const t = performance.now() / 1000;
      return { level, centroid: (Math.sin(t * 0.7) + 1) / 2 };
    };
  }, [getLevel]);

  return (
    <div
      className="kiosk-root"
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 20,
        padding: 24,
      }}
    >
      <div className="k-avatar-stage" style={{ width: 375, maxHeight: 'none' }}>
        <VrmAvatar state={state} getLevel={getLevel} getFeatures={getFeatures} />
      </div>
      <div style={{ display: 'flex', gap: 10 }}>
        {STATES.map((s) => (
          <button
            key={s}
            type="button"
            className={`k-btn ${s === state ? 'primary' : ''}`}
            style={{ padding: '10px 18px', fontSize: 16 }}
            onClick={() => setState(s)}
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
