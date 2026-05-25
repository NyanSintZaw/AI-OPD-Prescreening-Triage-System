import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import { resources, type AppLanguage } from './resources';

const STORAGE_KEY = 'hotline_language';

export function getStoredLanguage(): AppLanguage {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'th' || stored === 'en') {
    return stored;
  }
  return 'th';
}

export function setStoredLanguage(lang: AppLanguage): void {
  localStorage.setItem(STORAGE_KEY, lang);
  void i18n.changeLanguage(lang);
}

void i18n.use(initReactI18next).init({
  resources,
  lng: getStoredLanguage(),
  fallbackLng: 'en',
  interpolation: {
    escapeValue: false,
  },
});

export default i18n;
