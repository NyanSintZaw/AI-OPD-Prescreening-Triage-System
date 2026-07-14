/** Open the chrome-less patient slip in a new tab (popup-blocker safe with gesture). */
export function openPatientSlip(sessionId: string): Window | null {
  if (!sessionId) return null;
  return window.open(`/slip/${sessionId}`, '_blank', 'noopener,noreferrer');
}
