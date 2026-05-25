import { useTranslation } from 'react-i18next';

interface VoiceControlsProps {
  voiceEnabled: boolean;
  voiceSupported: boolean;
  isListening: boolean;
  speakerEnabled: boolean;
  speakerSupported: boolean;
  onMicClick: () => void;
  onSpeakerToggle: () => void;
}

export function VoiceControls({
  voiceEnabled,
  voiceSupported,
  isListening,
  speakerEnabled,
  speakerSupported,
  onMicClick,
  onSpeakerToggle,
}: VoiceControlsProps) {
  const { t } = useTranslation();
  const micDisabled = !voiceEnabled || !voiceSupported;

  return (
    <div className="voice-controls">
      <button
        type="button"
        className={`icon-btn ${isListening ? 'active' : ''}`}
        onClick={onMicClick}
        disabled={micDisabled}
        title={micDisabled ? t('voiceComingSoon') : t('speak')}
        aria-label={micDisabled ? t('voiceComingSoon') : t('speak')}
      >
        {isListening ? '🎙️' : '🎤'}
      </button>
      <button
        type="button"
        className={`icon-btn ${speakerEnabled ? 'active' : ''}`}
        onClick={onSpeakerToggle}
        disabled={!speakerSupported}
        title={speakerEnabled ? t('speakerOff') : t('speakerOn')}
        aria-label={speakerEnabled ? t('speakerOff') : t('speakerOn')}
      >
        {speakerEnabled ? '🔊' : '🔇'}
      </button>
    </div>
  );
}
