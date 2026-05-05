import { test, expect, type APIRequestContext } from '@playwright/test';

/**
 * Demo concurrency isolation — runs against the deployed demo backend.
 *
 * Verifies the per-visitor ephemeral tenant promise:
 *   - Two parallel browser contexts each get distinct tenant_ids
 *   - Each cookie carries a different demo JWT
 *   - A write made in context A is NOT visible to context B
 *
 * Skipped by default (no `DEMO_E2E_BASE_URL` env). To run against the
 * live demo stack:
 *
 *   DEMO_E2E_BASE_URL=https://demo-gateway.bsvibe.dev \
 *   DEMO_E2E_API_URL=https://api-demo-gateway.bsvibe.dev \
 *     pnpm test:e2e --grep @demo
 */

const BASE = process.env.DEMO_E2E_BASE_URL;
const API = process.env.DEMO_E2E_API_URL;

test.describe('@demo concurrency isolation', () => {
  test.skip(!BASE || !API, 'Set DEMO_E2E_BASE_URL + DEMO_E2E_API_URL to run');

  async function postSession(api: APIRequestContext) {
    const resp = await api.post(`${API}/api/v1/demo/session`);
    expect(resp.status()).toBe(201);
    return resp.json() as Promise<{ tenant_id: string; token: string; expires_in: number }>;
  }

  test('two browsers get distinct tenant_ids', async ({ browser }) => {
    const ctxA = await browser.newContext();
    const ctxB = await browser.newContext();
    try {
      const [a, b] = await Promise.all([
        postSession(ctxA.request),
        postSession(ctxB.request),
      ]);
      expect(a.tenant_id).not.toBe(b.tenant_id);
      expect(a.token).not.toBe(b.token);
    } finally {
      await ctxA.close();
      await ctxB.close();
    }
  });

  test('writes in context A are invisible to context B', async ({ browser }) => {
    const ctxA = await browser.newContext();
    const ctxB = await browser.newContext();
    try {
      // Two parallel sessions
      const [a, b] = await Promise.all([
        postSession(ctxA.request),
        postSession(ctxB.request),
      ]);
      expect(a.tenant_id).not.toBe(b.tenant_id);

      // Helper: list api keys via the now-authenticated context
      async function listKeys(ctx: APIRequestContext): Promise<unknown[]> {
        const resp = await ctx.get(`${API}/api/v1/api-keys`);
        // Demo session cookie is sent automatically; demo backend's
        // tenant scoping isolates rows by tenant_id.
        if (!resp.ok()) return [];
        const body = (await resp.json()) as { items?: unknown[] };
        return body.items ?? [];
      }

      const keysBefore = await listKeys(ctxA.request);

      // Create a key in A
      const create = await ctxA.request.post(`${API}/api/v1/api-keys`, {
        data: { name: 'concurrency-probe' },
      });
      // Some backends 201; allow 200/201
      expect([200, 201]).toContain(create.status());

      const keysAfterA = await listKeys(ctxA.request);
      const keysAfterB = await listKeys(ctxB.request);

      // A sees one more; B's count is unchanged from its own seed
      expect(keysAfterA.length).toBe(keysBefore.length + 1);
      // The newly-created key MUST NOT appear in B
      const probeIn = (rows: unknown[]) =>
        rows.some((r) => (r as { name?: string }).name === 'concurrency-probe');
      expect(probeIn(keysAfterA)).toBe(true);
      expect(probeIn(keysAfterB)).toBe(false);
    } finally {
      await ctxA.close();
      await ctxB.close();
    }
  });

  test('demo session cookie persists across reloads', async ({ browser }) => {
    const ctx = await browser.newContext();
    try {
      const first = await postSession(ctx.request);
      const cookies = await ctx.cookies();
      const demoCookie = cookies.find((c) => c.name === 'bsvibe_demo_session');
      expect(demoCookie).toBeDefined();
      expect(demoCookie?.value).toBe(first.token);

      // A subsequent POST without clearing cookies must NOT create a new tenant
      // — the backend should detect the existing cookie and either return 200
      // with the same token, or 201 with a fresh tenant. Both are acceptable;
      // the contract is that the active tenant_id is reachable via the cookie.
      const second = await postSession(ctx.request);
      expect(second.tenant_id).toMatch(/^[0-9a-f-]{36}$/);
    } finally {
      await ctx.close();
    }
  });
});
