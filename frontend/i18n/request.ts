/**
 * next-intl request config — composes the shared `@bsvibe/i18n`
 * namespaces (`common`, `auth`) with the BSGateway-local `gateway`
 * namespace.
 *
 * BSGateway pins `defaultLocale: 'en'` because the existing UI copy and
 * Playwright e2e suite assert on English. Korean is opt-in via the `/ko`
 * URL prefix produced by the `localePrefix: 'as-needed'` middleware.
 */
import { getRequestConfig as defineRequestConfig } from 'next-intl/server';
import {
  getRequestConfig as buildSharedConfig,
  resolveLocale,
} from '@bsvibe/i18n';

const GATEWAY_DEFAULT_LOCALE = 'en' as const;

export default defineRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = resolveLocale(requested, GATEWAY_DEFAULT_LOCALE);

  // BSGateway messages live at `frontend/messages/gateway.{en,ko}.json`,
  // shaped `{ nav: {...}, dashboard: {...}, ... }` — the same nested tree
  // the legacy react-i18next `translation.json` carried. Layering it as
  // the `gateway` namespace keeps every `t('nav.dashboard')` call working;
  // `buildSharedConfig` adds the shared `common` / `auth` namespaces.
  const file = (await import(`../messages/gateway.${locale}.json`)).default;

  const shared = await buildSharedConfig({
    locale,
    extra: { gateway: file },
  });

  return {
    locale,
    messages: shared.messages,
  };
});
