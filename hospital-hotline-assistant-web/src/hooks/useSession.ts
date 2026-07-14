import { useCallback, useEffect, useState } from 'react';
import type { AppLanguage } from '../i18n/resources';
import { getStoredLanguage, setStoredLanguage } from '../i18n';

const SESSION_KEY = 'hotline_session_id';
const PATIENT_NAME_KEY = 'hotline_patient_name';

export function useLanguage() {
  const [language, setLanguageState] = useState<AppLanguage>(getStoredLanguage);

  const setLanguage = useCallback((lang: AppLanguage) => {
    setStoredLanguage(lang);
    setLanguageState(lang);
  }, []);

  return { language, setLanguage };
}

export function getStoredSessionId(): string | null {
  return localStorage.getItem(SESSION_KEY);
}

export function setStoredSessionId(sessionId: string | null): void {
  if (sessionId) {
    localStorage.setItem(SESSION_KEY, sessionId);
  } else {
    localStorage.removeItem(SESSION_KEY);
  }
}

export function getStoredPatientName(): string | null {
  return localStorage.getItem(PATIENT_NAME_KEY);
}

export function setStoredPatientName(name: string | null): void {
  if (name) {
    localStorage.setItem(PATIENT_NAME_KEY, name);
  } else {
    localStorage.removeItem(PATIENT_NAME_KEY);
  }
}

export function useSessionStorage() {
  const [sessionId, setSessionIdState] = useState<string | null>(() => getStoredSessionId());

  const setSessionId = useCallback((id: string | null) => {
    setStoredSessionId(id);
    setSessionIdState(id);
    if (!id) {
      setStoredPatientName(null);
    }
  }, []);

  useEffect(() => {
    setSessionIdState(getStoredSessionId());
  }, []);

  return { sessionId, setSessionId };
}
