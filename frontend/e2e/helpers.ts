import { Page } from '@playwright/test';

const TENANT_ID = 'test-tenant-id';
const API_BASE = '/api/v1';

/**
 * Build a fake JWT (unsigned) with the given payload for testing.
 * The signature is empty — only the client-side base64 decode matters.
 */
function buildFakeJwt(payload: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({ alg: 'none', typ: 'JWT' }));
  const body = btoa(JSON.stringify(payload));
  return `${header}.${body}.fake`;
}

const FAKE_JWT = buildFakeJwt({
  sub: 'user-test-123',
  email: 'test@example.com',
  app_metadata: { tenant_id: TENANT_ID, role: 'admin' },
  exp: Math.floor(Date.now() / 1000) + 3600,
});

/**
 * Mock the auth.bsvibe.dev/api/session endpoint to return a valid session.
 * This replaces the old localStorage-based injectAuth.
 *
 * Phase B Batch 2: returns the full SessionEnvelope shape (`user` +
 * `tenants` + `active_tenant_id`). The legacy 3-field response was missing
 * `user`, which caused `<ProtectedRoute>` to redirect to /login and broke
 * protected-page e2e.
 */
export async function injectAuth(page: Page) {
  await page.route('**/auth.bsvibe.dev/api/session', (route) => {
    const method = route.request().method();
    if (method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user: {
            id: 'user-test-123',
            email: 'test@example.com',
            name: 'Test User',
          },
          tenants: [
            {
              id: TENANT_ID,
              name: 'Test Tenant',
              slug: 'test-tenant',
              plan: 'team',
              type: 'company',
              role: 'admin',
            },
          ],
          active_tenant_id: TENANT_ID,
          access_token: FAKE_JWT,
          refresh_token: 'fake-refresh-token',
          expires_in: 3600,
        }),
      });
    }
    // DELETE (logout) — just return success
    if (method === 'DELETE') {
      return route.fulfill({ status: 200, body: '{}' });
    }
    return route.continue();
  });
}

/**
 * Mock the session endpoint to return 401 (unauthenticated).
 */
export async function mockUnauthSession(page: Page) {
  await page.route('**/auth.bsvibe.dev/api/session', (route) => {
    return route.fulfill({ status: 401, body: '{"error":"no session"}' });
  });
}

/** Navigate as an unauthenticated user. */
export async function gotoUnauth(page: Page, path: string) {
  await mockUnauthSession(page);
  await page.goto(path);
}

/** Standard API path builder */
export function apiPath(path: string): string {
  return `${API_BASE}/tenants/${TENANT_ID}${path}`;
}

/** Mock a GET endpoint returning JSON */
export async function mockGet(page: Page, pathSuffix: string, body: unknown) {
  await page.route(`**${apiPath(pathSuffix)}*`, (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    }
    return route.continue();
  });
}

/** Mock a POST endpoint returning JSON */
export async function mockPost(page: Page, pathSuffix: string, body: unknown, status = 200) {
  await page.route(`**${apiPath(pathSuffix)}*`, (route) => {
    if (route.request().method() === 'POST') {
      return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    }
    return route.continue();
  });
}

/** Mock tenant info endpoint */
export async function mockTenantInfo(page: Page) {
  await page.route(`**${API_BASE}/tenants/${TENANT_ID}`, (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: TENANT_ID, name: 'Test Tenant', slug: 'test-tenant' }),
      });
    }
    return route.continue();
  });
}

// ---- Fixture data ----

export const MOCK_RULES = [
  {
    id: 'rule-1',
    tenant_id: TENANT_ID,
    name: 'code-review-and-debugging',
    priority: 0,
    is_active: true,
    is_default: false,
    target_model: 'gpt-4o',
    conditions: [
      {
        id: 'c1',
        condition_type: 'intent',
        field: 'classified_intent',
        operator: 'eq',
        value: 'code-review-and-debugging',
        negate: false,
      },
    ],
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-01T00:00:00Z',
  },
  {
    id: 'rule-2',
    tenant_id: TENANT_ID,
    name: 'Default Fallback',
    priority: 99,
    is_active: true,
    is_default: true,
    target_model: 'gpt-4o-mini',
    conditions: [],
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-01T00:00:00Z',
  },
];

export const MOCK_INTENTS = [
  {
    id: 'intent-1',
    tenant_id: TENANT_ID,
    name: 'code-review-and-debugging',
    description: 'Code review and debugging requests',
    threshold: 0.7,
    is_active: true,
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-01T00:00:00Z',
  },
];

export const MOCK_EXAMPLES = [
  {
    id: 'example-1',
    intent_id: 'intent-1',
    text: 'Please review this code',
    created_at: '2026-03-01T00:00:00Z',
  },
  {
    id: 'example-2',
    intent_id: 'intent-1',
    text: 'Help me debug this error',
    created_at: '2026-03-01T00:00:00Z',
  },
];

export const MOCK_MODELS = [
  {
    id: 'model-1',
    tenant_id: TENANT_ID,
    model_name: 'gpt-4o',
    provider: 'openai',
    litellm_model: 'openai/gpt-4o',
    api_base: null,
    is_active: true,
    extra_params: {},
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-01T00:00:00Z',
  },
  {
    id: 'model-2',
    tenant_id: TENANT_ID,
    model_name: 'claude-sonnet',
    provider: 'anthropic',
    litellm_model: 'anthropic/claude-3-5-sonnet',
    api_base: null,
    is_active: true,
    extra_params: {},
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-01T00:00:00Z',
  },
  {
    id: 'model-3',
    tenant_id: TENANT_ID,
    model_name: 'gemini-pro',
    provider: 'google',
    litellm_model: 'google/gemini-pro',
    api_base: null,
    is_active: false,
    extra_params: {},
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-01T00:00:00Z',
  },
];

export const MOCK_USAGE = {
  total_requests: 12345,
  total_tokens: 2_500_000,
  by_model: {
    'openai/gpt-4o': { requests: 8000, tokens: 1_800_000 },
    'anthropic/claude-3-5-sonnet': { requests: 3000, tokens: 500_000 },
    'google/gemini-pro': { requests: 1345, tokens: 200_000 },
  },
  by_rule: {
    'High Priority Router': 8000,
    'Default Fallback': 4345,
  },
  daily_breakdown: [
    { date: '2026-03-23', requests: 1500, tokens: 300000 },
    { date: '2026-03-24', requests: 1800, tokens: 360000 },
    { date: '2026-03-25', requests: 2000, tokens: 400000 },
    { date: '2026-03-26', requests: 1700, tokens: 340000 },
    { date: '2026-03-27', requests: 2200, tokens: 440000 },
    { date: '2026-03-28', requests: 1900, tokens: 380000 },
    { date: '2026-03-29', requests: 1245, tokens: 280000 },
  ],
};

export const MOCK_AUDIT_LOGS = [
  {
    id: 'log-1',
    tenant_id: TENANT_ID,
    actor: 'user-abc12345-6789',
    action: 'created_rule',
    resource_type: 'rule',
    resource_id: 'rule-1-abcdef',
    details: {},
    created_at: '2026-03-29T10:00:00Z',
  },
  {
    id: 'log-2',
    tenant_id: TENANT_ID,
    actor: 'user-abc12345-6789',
    action: 'deleted_model',
    resource_type: 'model',
    resource_id: 'model-x-12345',
    details: {},
    created_at: '2026-03-28T15:30:00Z',
  },
];

export const MOCK_API_KEYS = [
  {
    id: 'key-1',
    tenant_id: TENANT_ID,
    name: 'production',
    key_prefix: 'bsg_prod_abc',
    scopes: ['*'],
    is_active: true,
    expires_at: null,
    last_used_at: '2026-03-29T08:00:00Z',
    created_at: '2026-03-01T00:00:00Z',
  },
  {
    id: 'key-2',
    tenant_id: TENANT_ID,
    name: 'staging',
    key_prefix: 'bsg_stag_xyz',
    scopes: ['*'],
    is_active: true,
    expires_at: null,
    last_used_at: null,
    created_at: '2026-03-15T00:00:00Z',
  },
  {
    id: 'key-3',
    tenant_id: TENANT_ID,
    name: 'revoked-key',
    key_prefix: 'bsg_old_def',
    scopes: ['*'],
    is_active: false,
    expires_at: null,
    last_used_at: '2026-02-01T00:00:00Z',
    created_at: '2026-01-01T00:00:00Z',
  },
];

export const MOCK_TEST_RESULT = {
  matched_rule: { id: 'rule-1', name: 'High Priority Router', priority: 1 },
  target_model: 'openai/gpt-4o',
  evaluation_trace: [
    { rule: 'High Priority Router', matched: true },
    { rule: 'Default Fallback', matched: false },
  ],
  context: { complexity_score: 85, token_count: 120, model: 'gpt-4o' },
};
