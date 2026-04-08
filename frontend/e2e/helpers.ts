import { Page } from '@playwright/test';

const TENANT_ID = 'test-tenant-id';
const API_BASE = '/api/v1';

/**
 * Inject fake auth tokens into localStorage so the app considers us logged in.
 * Must be called before navigating to any page.
 */
export async function injectAuth(page: Page) {
  await page.addInitScript(() => {
    // BSVibeAuth stores user in localStorage under 'bsvibe_user'
    // expiresAt is in seconds (unix timestamp), not milliseconds
    const fakeUser = {
      id: 'user-test-123',
      accessToken: 'fake-access-token',
      refreshToken: 'fake-refresh-token',
      tenantId: 'test-tenant-id',
      role: 'admin',
      email: 'test@example.com',
      expiresAt: Math.floor(Date.now() / 1000) + 3600,
    };
    localStorage.setItem('bsvibe_user', JSON.stringify(fakeUser));
    sessionStorage.setItem('bsvibe_tenant_name', 'Test Tenant');
  });
}

/** Standard API path builder */
export function apiPath(path: string): string {
  return `${API_BASE}/tenants/${TENANT_ID}${path}`;
}

/**
 * Set the `bsvibe_skip_sso` localStorage flag so `BSVibeAuth.checkSession()`
 * short-circuits and behaves as fully unauthenticated. This avoids the
 * silent-SSO redirect that would otherwise navigate the test off-origin.
 *
 * The query-param escape hatch (`?sso_error=...`) does not work here because
 * React's `StrictMode` invokes effects twice in dev — the first run strips
 * the param via `replaceState`, then the second run sees a clean URL and
 * fires the silent-check anyway, causing a redirect loop.
 */
export async function skipSso(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('bsvibe_skip_sso', '1');
  });
}

/** Navigate as an unauthenticated user without leaving the LoginPage. */
export async function gotoUnauth(page: Page, path: string) {
  await skipSso(page);
  await page.goto(path);
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

/** Mock tenant info endpoint (used by useAuth to fetch tenant name) */
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
