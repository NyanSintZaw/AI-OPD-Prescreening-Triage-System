import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { AppLanguage } from '../i18n/resources';
import { setStoredLanguage } from '../i18n';

const SESSION_KEY = 'hotline_session_id';
const PATIENT_NAME_KEY = 'hotline_patient_name';

/**
 * The app's language, read from i18next rather than mirrored beside it.
 *
 * This used to keep its own `useState`, which made one copy per calling
 * component: the header switcher updated the page that owned it and nothing
 * else. Anything reading `language` to pick a `name_th` vs `name_en` — the
 * dashboard, the session log's routing column — went on rendering Thai inside
 * an English portal until it happened to remount.
 *
 * `setStoredLanguage` already calls `i18n.changeLanguage`, so i18next was
 * always the real source of truth; `useTranslation` subscribes to it, so every
 * caller now re-renders on a switch.
 */
export function useLanguage() {
  const { i18n } = useTranslation();

  const setLanguage = useCallback((lang: AppLanguage) => setStoredLanguage(lang), []);

  // i18next can hand back a region tag ("en-US") if it is ever configured to
  // detect one; the app only has two blocks and must not ask for a third.
  const language: AppLanguage = i18n.language === 'en' ? 'en' : 'th';
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
