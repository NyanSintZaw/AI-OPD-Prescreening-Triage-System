/**
 * Slip code shown on the patient's printed slip, derived from the session
 * id. The nurse at the destination department types it to find the session.
 *
 * Must match the backend (`app/services/slip_code.py`) and the patient slip
 * renderer (`PatientIdPass.shortVisitId`) exactly.
 */
export function slipCode(sessionId: string): string {
  const clean = sessionId.replace(/[^a-zA-Z0-9]/g, '').toUpperCase();
  if (clean.length <= 8) return clean;
  return `MCH-${clean.slice(0, 4)}-${clean.slice(-4)}`;
}

/** Normalize a slip code / free text for tolerant matching (drop separators). */
export function slipSearchKey(value: string): string {
  return value.replace(/[^a-zA-Z0-9]/g, '').toUpperCase();
}
