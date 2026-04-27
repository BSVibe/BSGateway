/**
 * BSGateway i18n setup (Phase C — gateway namespace).
 *
 * Phase C decision (~/Docs/BSVibe_Execution_Lockin.md §Phase C):
 *  - Static export (`output: 'export'`) is incompatible with next-intl's
 *    middleware-driven locale routing (middleware needs Edge runtime; static
 *    export emits pre-rendered HTML with no runtime). We keep `react-i18next`
 *    which is fully client-side and ships untouched through static export.
 *  - `@bsvibe/i18n` shared lib (next-intl based) is therefore NOT integrated
 *    here. The decision is recorded in the PR description and the lock-in doc.
 *  - Locale persists via localStorage (`bsgateway.locale`) so the static
 *    bundle survives reloads. Default is `en` to match the existing E2E
 *    suite which asserts English copy.
 */
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import ko from './ko/translation.json';
import en from './en/translation.json';

export const SUPPORTED_LOCALES = ['ko', 'en'] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];
export const DEFAULT_LOCALE: Locale = 'en';
export const LOCALE_STORAGE_KEY = 'bsgateway.locale';

function detectInitialLocale(): Locale {
  if (typeof window === 'undefined') return DEFAULT_LOCALE;
  try {
    const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
    if (stored && (SUPPORTED_LOCALES as readonly string[]).includes(stored)) {
      return stored as Locale;
    }
  } catch {
    // localStorage may throw in privacy mode — fall through to default.
  }
  return DEFAULT_LOCALE;
}

i18n.use(initReactI18next).init({
  resources: {
    ko: { translation: ko },
    en: { translation: en },
  },
  lng: detectInitialLocale(),
  fallbackLng: 'en',
  interpolation: {
    escapeValue: false,
  },
});

export function setLocale(locale: Locale): void {
  if (!(SUPPORTED_LOCALES as readonly string[]).includes(locale)) return;
  i18n.changeLanguage(locale);
  if (typeof window !== 'undefined') {
    try {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
    } catch {
      // ignore storage failures
    }
  }
}

export function getLocale(): Locale {
  const current = i18n.language;
  return (SUPPORTED_LOCALES as readonly string[]).includes(current)
    ? (current as Locale)
    : DEFAULT_LOCALE;
}

export default i18n;
