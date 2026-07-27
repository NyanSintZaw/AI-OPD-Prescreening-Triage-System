import { VoiceControls } from 'hospital-hotline-assistant-web';

const noop = () => {};

export const Idle = () => (
  <VoiceControls
    voiceEnabled
    voiceSupported
    isListening={false}
    speakerEnabled
    speakerSupported
    onMicClick={noop}
    onSpeakerToggle={noop}
  />
);

export const Listening = () => (
  <VoiceControls
    voiceEnabled
    voiceSupported
    isListening
    speakerEnabled
    speakerSupported
    onMicClick={noop}
    onSpeakerToggle={noop}
  />
);

export const MicUnavailableSpeakerMuted = () => (
  <VoiceControls
    voiceEnabled={false}
    voiceSupported={false}
    isListening={false}
    speakerEnabled={false}
    speakerSupported
    onMicClick={noop}
    onSpeakerToggle={noop}
  />
);
