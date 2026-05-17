import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { notFound } from 'next/navigation';
import { getMessages, setRequestLocale } from 'next-intl/server';
import { BSVibeIntlProvider, isSupportedLocale } from '@bsvibe/i18n';
import './globals.css';
import { AppShell } from '@/src/components/layout/AppShell';

export const metadata: Metadata = {
  title: 'BSGateway Dashboard',
  icons: {
    icon: '/favicon.svg',
  },
};

// next-intl `[locale]` segment — middleware (`localePrefix: 'as-needed'`,
// default `en`) routes English at the bare path and Korean under `/ko`.
export function generateStaticParams() {
  return [{ locale: 'ko' }, { locale: 'en' }];
}

// Pinned IANA time zone. Without an explicit zone, `use-intl`'s client
// provider emits an `ENVIRONMENT_FALLBACK` error during static generation
// (the server prerender and client hydration would otherwise format dates
// against different host time zones). Must match `i18n/request.ts`.
// https://next-intl.dev/docs/configuration#time-zone
const TIME_ZONE = 'UTC';

/**
 * Root layout for BSGateway — owns `<html>` because the next-intl
 * `[locale]` pattern makes `app/[locale]/layout.tsx` the root layout
 * (there is no `app/layout.tsx`). It keeps everything the legacy root
 * layout had — metadata, the font + Material Symbols stylesheet links,
 * `globals.css` import, the `<AppShell>` chrome — and adds the next-intl
 * plumbing: locale guard, `setRequestLocale`, message load, and
 * `BSVibeIntlProvider`.
 */
export default async function RootLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!isSupportedLocale(locale)) {
    notFound();
  }
  // Tell next-intl which locale this server render is for so any RSC
  // `getTranslations()` calls in nested layouts/pages resolve correctly.
  setRequestLocale(locale);
  const messages = await getMessages();

  return (
    <html lang={locale} className="dark">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        {/* Google Fonts loaded via stylesheet link rather than next/font so
            the Material Symbols variable axes (wght/FILL) are available; the
            App Router root layout is the single page these load on. */}
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link
          href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <BSVibeIntlProvider locale={locale} messages={messages} timeZone={TIME_ZONE}>
          <AppShell>{children}</AppShell>
        </BSVibeIntlProvider>
      </body>
    </html>
  );
}
