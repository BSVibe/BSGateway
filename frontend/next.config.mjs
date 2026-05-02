import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Dev rewrites run only in `next dev`; static export forbids them.
const isDev = process.env.NODE_ENV !== 'production';

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: ['bsserver'],
  devIndicators: false,
  // Pin tracing root to the frontend directory so the parent repo is not
  // inferred as the workspace root during static export builds.
  outputFileTracingRoot: __dirname,

  // Static export preserves the existing FastAPI deploy contract: the backend
  // mounts the build directory at `/dashboard` via `StaticFiles(html=True)`
  // (`bsgateway/api/app.py`). All pages here are static — no Server
  // Components with runtime data, no Route Handlers — so `output: 'export'`
  // works. Vercel auto-detects this and serves the static output directly.
  output: 'export',
  // FastAPI's StaticFiles needs each sub-route to resolve to a directory's
  // index.html (e.g. `/dashboard/rules/` → `rules/index.html`).
  trailingSlash: true,
  // Emit to `dist/` so the existing Dockerfile + FRONTEND_DIST_DIR env stay
  // valid (`COPY frontend/dist`). Replaces Vite's `dist/` output.
  distDir: 'dist',
  images: {
    // Static export disables Image Optimization. The current UI doesn't use
    // <Image>, but make the constraint explicit.
    unoptimized: true,
  },

  // Replaces the Vite dev-server proxy: forward `/api/*` to the backend so
  // dev fetches succeed without CORS. Only enabled in `next dev` — incompatible
  // with `output: 'export'` at build time.
  ...(isDev
    ? {
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
      }
    : {}),
};

export default nextConfig;
