/**
 * BSGateway i18n middleware.
 *
 * Uses the BSVibe shared `@bsvibe/i18n/middleware` factory so locale
 * routing stays consistent across all consumer products. BSGateway pins
 * `defaultLocale: 'en'` (overriding the package default of `ko`) because
 * the existing UI copy and Playwright e2e suite assert on English. Korean
 * is opt-in via the `/ko/...` URL prefix.
 *
 * This is i18n-only — BSGateway auth is gated client-side in
 * `src/components/layout/AppShell.tsx` (the prod shell renders
 * `<LoginPage>` when unauthenticated). There is no auth cookie redirect
 * here, deliberately.
 */
import { createI18nMiddleware } from '@bsvibe/i18n/middleware';

export default createI18nMiddleware({
  locales: ['ko', 'en'],
  defaultLocale: 'en',
  localePrefix: 'as-needed',
});

// NOTE: Next.js parses `config.matcher` statically — spread operators or
// computed values are rejected (`Invalid page config`). The literal mirrors
// `defaultMatcher` from `@bsvibe/i18n/middleware`.
export const config = {
  matcher: ['/((?!api|_next|_vercel|.*\\..*).*)'],
};
