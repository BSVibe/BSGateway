import path from 'node:path';
import { fileURLToPath } from 'node:url';
import createNextIntlPlugin from 'next-intl/plugin';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const withNextIntl = createNextIntlPlugin('./i18n/request.ts');

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: ['bsserver'],
  devIndicators: false,
  // Pin tracing root to the frontend directory so the parent repo is not
  // inferred as the workspace root during builds.
  outputFileTracingRoot: __dirname,

  // i18n adoption: `output: 'export'` is dropped — next-intl's
  // middleware-driven `[locale]` routing needs the Edge runtime, which a
  // static export cannot provide. This is now a real Next.js build. Prod
  // is already a standalone Vercel deploy, so prod is unaffected; the
  // backend `/dashboard` StaticFiles mount is retired in a follow-up PR.

  // Forward `/api/*` to the backend so dev fetches succeed without CORS.
  async rewrites() {
    const backend =
      process.env.VITE_PROXY_TARGET ||
      process.env.NEXT_PUBLIC_API_URL ||
      'http://localhost:8000';
    const target = backend.endsWith('/') ? backend.slice(0, -1) : backend;
    return [
      {
        source: '/api/:path*',
        destination: `${target}/api/:path*`,
      },
    ];
  },
};

export default withNextIntl(nextConfig);
