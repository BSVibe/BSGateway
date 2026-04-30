'use client';

import { useTranslation } from 'react-i18next';
import { SUPPORTED_LOCALES, setLocale, type Locale } from '../../i18n';

/**
 * Compact ko/en toggle. Persists to localStorage via setLocale().
 *
 * Rendered in the sidebar footer so it's reachable from every route without
 * eating header space. Uses i18n.language as the source of truth so that
 * any other locale change (programmatic / future detection) reflects here
 * automatically.
 */
export function LanguageSwitcher() {
  const { t, i18n } = useTranslation();
  const current = i18n.language as Locale;

  return (
    <div
      className="flex items-center gap-1 px-1.5 py-1.5 rounded-lg bg-surface-container/50"
      role="group"
      aria-label={t('language.label')}
    >
      {SUPPORTED_LOCALES.map((locale) => {
        const active = current === locale;
        return (
          <button
            key={locale}
            type="button"
            onClick={() => setLocale(locale)}
            aria-pressed={active}
            className={`min-h-10 min-w-10 px-2 py-1 text-[10px] font-bold uppercase tracking-widest rounded transition-colors ${
              active
                ? 'bg-primary-container/30 text-on-primary-container'
                : 'text-on-surface-variant hover:text-on-surface'
            }`}
          >
            {locale}
          </button>
        );
      })}
    </div>
  );
}
