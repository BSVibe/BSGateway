# BSGateway Dashboard

Next.js 15 (App Router) + React 19 + Tailwind 4.

Migrated from Vite + React Router under Phase Z; see
[`MIGRATION_NOTES.md`](../../BSVibe-Auth/phase0/auth-app/MIGRATION_NOTES.md)
for the cross-asset baseline.

## Scripts

```bash
pnpm install        # install deps
pnpm run dev        # Next dev server on :5173 (matches the old Vite port)
pnpm run build      # Static export -> frontend/dist/ (FastAPI serves it under /dashboard)
pnpm run preview    # Serve the built dist/ over localhost:5173 via `npx serve`
pnpm run lint       # ESLint flat config
pnpm run test:e2e   # Playwright suite (boots `next dev`)
```

## Environment

| Variable                 | Visibility | Notes |
|--------------------------|-----------|-------|
| `NEXT_PUBLIC_AUTH_URL`   | client    | BSVibe-Auth host (defaults to `https://auth.bsvibe.dev`) |
| `NEXT_PUBLIC_API_URL`    | client    | Backend origin; `/api/v1` is appended automatically |
| `VITE_PROXY_TARGET`      | dev only  | Legacy fallback for the dev `rewrites()` proxy |

`next dev` proxies `/api/*` to `NEXT_PUBLIC_API_URL` (or
`VITE_PROXY_TARGET`, defaulting to `http://localhost:8000`). The static export
build (`output: 'export'`) drops the rewrites — production deploys point the
client at the backend directly via `NEXT_PUBLIC_API_URL`.

## Deploy

- **Vercel**: framework auto-detected (Next.js). The static export under
  `frontend/dist/` is served directly.
- **Self-hosted (Docker)**: `deploy/Dockerfile` builds `frontend/dist/` and
  the FastAPI backend mounts it at `/dashboard` via
  `StaticFiles(html=True)` (`bsgateway/api/app.py`).
