/**
 * BSGateway i18n middleware.
 *
 * Wraps the BSVibe shared `@bsvibe/i18n/middleware` factory so locale
 * routing stays consistent across all consumer products. BSGateway pins
 * `defaultLocale: 'en'` (overriding the package default of `ko`) because
 * the existing UI copy and Playwright e2e suite assert on English. Korean
 * is opt-in via the `/ko/...` URL prefix.
 *
 * This is i18n-only — BSGateway auth is gated client-side in
 * `src/components/layout/AppShell.tsx` (the prod shell renders
 * `<LoginPage>` when unauthenticated). There is no auth cookie redirect
 * here, deliberately.
 *
 * ── Re-entrancy guard (production redirect-loop fix) ───────────────────
 * With `localePrefix: 'as-needed'` + `defaultLocale: 'en'`, next-intl's
 * middleware handles a request to `/` by *rewriting* it to `/en`
 * (`NextResponse.rewrite`, status 200). In `next start` — but NOT in
 * `next dev` — Next.js 15's production route resolver
 * (`router-utils/resolve-routes.js`) re-runs middleware on that rewritten
 * internal path `/en`. On that second pass next-intl sees a
 * default-locale-prefixed path and *redirects* `/en` → `/` (307) to strip
 * the prefix. Next merges the two passes into one response carrying both
 * `x-middleware-rewrite: /en` AND `location: /` (307) — the browser
 * follows `location` straight back to `/`, an infinite redirect loop.
 *
 * next-intl's own `next()` rewrite sets the `x-next-intl-locale` request
 * header on the rewritten subrequest. Its presence is the unambiguous
 * signal "this is an internal re-entrant pass next-intl already resolved"
 * — so we short-circuit with `NextResponse.next()` and never let the
 * second pass emit the prefix-stripping redirect. `next dev` never enters
 * the second pass, so this is a no-op there.
 */
import { createI18nMiddleware } from '@bsvibe/i18n/middleware';
import { NextResponse, type NextRequest } from 'next/server';

// next-intl sets this request header on its `next()` rewrite subrequest
// (see `HEADER_LOCALE_NAME` in next-intl's `shared/constants`).
const HEADER_LOCALE_NAME = 'x-next-intl-locale';

const i18nMiddleware = createI18nMiddleware({
  locales: ['ko', 'en'],
  defaultLocale: 'en',
  localePrefix: 'as-needed',
});

export default function middleware(request: NextRequest) {
  // Re-entrant pass on a next-intl-rewritten internal path — the locale is
  // already resolved, so do not let next-intl re-route (which would emit
  // the `as-needed` prefix-strip redirect and create the loop).
  if (request.headers.has(HEADER_LOCALE_NAME)) {
    return NextResponse.next();
  }
  return i18nMiddleware(request);
}

// NOTE: Next.js parses `config.matcher` statically — spread operators or
// computed values are rejected (`Invalid page config`). The literal mirrors
// `defaultMatcher` from `@bsvibe/i18n/middleware`.
export const config = {
  matcher: ['/((?!api|_next|_vercel|.*\\..*).*)'],
};
