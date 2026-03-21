/**
 * Shared mock API helpers for E2E tests.
 * Provides mock data + route interception so tests run without a real backend.
 */
import { Page } from '@playwright/test';

// ── Mock tenant ──────────────────────────────────────────────────────
export const TENANT = {
  id: '144154d8-d030-43ba-a75b-f37674524f80',
  slug: 'dev-team',
  name: 'Dev Team',
  token:
    'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0ZW5hbnRfaWQiOiIxNDQxNTRkOCIsInNjb3BlcyI6WyJjaGF0IiwiYWRtaW4iXX0.mock',
};

export const API_KEY = 'bsg_dev-test-key-do-not-use-in-production-000';

// ── Mock data ────────────────────────────────────────────────────────
export const MOCK_MODELS = [
  {
    id: '806c9083-7169-45fe-8590-0982668abcf0',
    tenant_id: TENANT.id,
    model_name: 'claude-sonnet',
    provider: 'anthropic',
    litellm_model: 'anthropic/claude-sonnet-4-20250514',
    api_base: null,
    is_active: true,
    extra_params: {},
    created_at: '2026-03-16T13:30:02.805696+00:00',
    updated_at: '2026-03-16T13:30:02.805696+00:00',
  },
  {
    id: '8f98bca2-e586-4d04-a6bd-1dd637125575',
    tenant_id: TENANT.id,
    model_name: 'gpt-4o',
    provider: 'openai',
    litellm_model: 'openai/gpt-4o',
    api_base: null,
    is_active: true,
    extra_params: {},
    created_at: '2026-03-16T13:30:02.805696+00:00',
    updated_at: '2026-03-16T13:30:02.805696+00:00',
  },
  {
    id: '37825e85-6e21-4388-be1a-29bdbcd79744',
    tenant_id: TENANT.id,
    model_name: 'gpt-4o-mini',
    provider: 'openai',
    litellm_model: 'openai/gpt-4o-mini',
    api_base: null,
    is_active: false,
    extra_params: {},
    created_at: '2026-03-16T13:30:02.805696+00:00',
    updated_at: '2026-03-16T13:30:02.805696+00:00',
  },
];

export const MOCK_RULES = [
  {
    id: 'r-001',
    tenant_id: TENANT.id,
    name: 'High-priority rule',
    priority: 1,
    is_active: true,
    is_default: false,
    target_model: 'claude-sonnet',
    conditions: [
      {
        id: 'c-001',
        condition_type: 'keyword',
        field: 'content',
        operator: 'contains',
        value: 'urgent',
        negate: false,
      },
    ],
    created_at: '2026-03-16T14:00:00+00:00',
    updated_at: '2026-03-16T14:00:00+00:00',
  },
  {
    id: 'r-002',
    tenant_id: TENANT.id,
    name: 'Default fallback',
    priority: 100,
    is_active: true,
    is_default: true,
    target_model: 'gpt-4o-mini',
    conditions: [],
    created_at: '2026-03-16T14:00:00+00:00',
    updated_at: '2026-03-16T14:00:00+00:00',
  },
];

export const MOCK_INTENTS = [
  {
    id: 'i-001',
    tenant_id: TENANT.id,
    name: 'summarization',
    description: 'Requests asking to summarize content',
    examples: ['Please summarize this article', 'TL;DR of the above'],
    target_model: 'gpt-4o',
    is_active: true,
    created_at: '2026-03-17T10:00:00+00:00',
    updated_at: '2026-03-17T10:00:00+00:00',
  },
  {
    id: 'i-002',
    tenant_id: TENANT.id,
    name: 'code-generation',
    description: 'Requests to generate code',
    examples: ['Write a function that...'],
    target_model: 'claude-sonnet',
    is_active: false,
    created_at: '2026-03-17T10:00:00+00:00',
    updated_at: '2026-03-17T10:00:00+00:00',
  },
];

export const MOCK_USAGE = {
  total_requests: 1247,
  total_tokens: 523800,
  success_rate: 0.986,
  by_model: {
    'gpt-4o': 520,
    'claude-sonnet': 430,
    'gpt-4o-mini': 297,
  },
  by_rule: {
    'High-priority rule': 430,
    'Default fallback': 817,
  },
  daily_breakdown: {
    '2026-03-13': 145,
    '2026-03-14': 189,
    '2026-03-15': 210,
    '2026-03-16': 178,
    '2026-03-17': 195,
    '2026-03-18': 162,
    '2026-03-19': 168,
  },
};

export const MOCK_AUDIT_LOGS = [
  {
    id: 'al-001',
    tenant_id: TENANT.id,
    actor: '806c9083-7169-45fe-8590-0982668abcf0',
    action: 'model.created',
    resource_type: 'model',
    resource_id: '806c9083-7169-45fe-8590-0982668abcf0',
    details: { model_name: 'claude-sonnet' },
    created_at: '2026-03-19T14:45:00+00:00',
  },
  {
    id: 'al-002',
    tenant_id: TENANT.id,
    actor: '806c9083-7169-45fe-8590-0982668abcf0',
    action: 'rule.created',
    resource_type: 'rule',
    resource_id: 'r-001',
    details: { name: 'High-priority rule' },
    created_at: '2026-03-19T14:30:00+00:00',
  },
  {
    id: 'al-003',
    tenant_id: TENANT.id,
    actor: '806c9083-7169-45fe-8590-0982668abcf0',
    action: 'model.deleted',
    resource_type: 'model',
    resource_id: 'old-model-id-12345',
    details: null,
    created_at: '2026-03-19T14:00:00+00:00',
  },
];

export const MOCK_TEST_RESULT = {
  selected_model: 'claude-sonnet',
  matched_rule: 'High-priority rule',
  latency_ms: 4.2,
  conditions_matched: {
    'keyword:content:contains:urgent': true,
  },
};

// ── Helpers ──────────────────────────────────────────────────────────

/** Inject auth state into sessionStorage before page load. */
export async function setupAuth(page: Page) {
  await page.addInitScript(
    ({ t }) => {
      sessionStorage.setItem('bsg_token', t.token);
      sessionStorage.setItem('bsg_tenant_id', t.id);
      sessionStorage.setItem('bsg_tenant_slug', t.slug);
      sessionStorage.setItem('bsg_tenant_name', t.name);
    },
    { t: TENANT },
  );
}

/** Clear auth state from sessionStorage. */
export async function clearAuth(page: Page) {
  await page.addInitScript(() => {
    sessionStorage.removeItem('bsg_token');
    sessionStorage.removeItem('bsg_tenant_id');
    sessionStorage.removeItem('bsg_tenant_slug');
    sessionStorage.removeItem('bsg_tenant_name');
  });
}

/**
 * Set up full API route mocking. Supports mutable lists so CRUD
 * operations within a test reflect immediately.
 */
export async function setupApiMocks(page: Page) {
  // Mutable copies so tests can observe mutations
  let models = [...MOCK_MODELS];
  let rules = [...MOCK_RULES];
  let intents = [...MOCK_INTENTS];

  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();

    // ── Auth ───────────────────────────────────────
    if (path.endsWith('/auth/token') && method === 'POST') {
      const body = route.request().postDataJSON();
      if (body?.api_key === API_KEY) {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            token: TENANT.token,
            tenant_id: TENANT.id,
            tenant_slug: TENANT.slug,
            tenant_name: TENANT.name,
            scopes: ['chat', 'admin'],
          }),
        });
      }
      return route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Invalid or expired API key' }),
      });
    }

    // ── Models ─────────────────────────────────────
    if (path.match(/\/tenants\/[^/]+\/models$/) && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(models),
      });
    }
    if (path.match(/\/tenants\/[^/]+\/models$/) && method === 'POST') {
      const body = route.request().postDataJSON();
      const provider = (body.litellm_model || '').split('/')[0] || 'unknown';
      const newModel = {
        id: `m-${Date.now()}`,
        tenant_id: TENANT.id,
        model_name: body.model_name,
        provider,
        litellm_model: body.litellm_model,
        api_base: body.api_base || null,
        is_active: true,
        extra_params: body.extra_params || {},
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      models = [...models, newModel];
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(newModel),
      });
    }
    if (path.match(/\/tenants\/[^/]+\/models\/[^/]+$/) && method === 'DELETE') {
      const modelId = path.split('/').pop()!;
      models = models.filter((m) => m.id !== modelId);
      return route.fulfill({ status: 204 });
    }

    // ── Rules ──────────────────────────────────────
    if (path.match(/\/tenants\/[^/]+\/rules$/) && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(rules),
      });
    }
    if (path.match(/\/tenants\/[^/]+\/rules$/) && method === 'POST') {
      const body = route.request().postDataJSON();
      const newRule = {
        id: `r-${Date.now()}`,
        tenant_id: TENANT.id,
        name: body.name,
        priority: body.priority,
        is_active: true,
        is_default: body.is_default || false,
        target_model: body.target_model,
        conditions: [],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      rules = [...rules, newRule];
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(newRule),
      });
    }
    if (path.match(/\/tenants\/[^/]+\/rules\/test$/) && method === 'POST') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_TEST_RESULT),
      });
    }
    if (
      path.match(/\/tenants\/[^/]+\/rules\/[^/]+$/) &&
      !path.includes('/test') &&
      method === 'DELETE'
    ) {
      const ruleId = path.split('/').pop()!;
      rules = rules.filter((r) => r.id !== ruleId);
      return route.fulfill({ status: 204 });
    }

    // ── Intents ────────────────────────────────────
    if (path.match(/\/tenants\/[^/]+\/intents$/) && method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(intents),
      });
    }
    if (path.match(/\/tenants\/[^/]+\/intents$/) && method === 'POST') {
      const body = route.request().postDataJSON();
      const newIntent = {
        id: `i-${Date.now()}`,
        tenant_id: TENANT.id,
        name: body.name,
        description: body.description || null,
        examples: body.examples || [],
        target_model: body.target_model || null,
        is_active: true,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      intents = [...intents, newIntent];
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(newIntent),
      });
    }
    if (path.match(/\/tenants\/[^/]+\/intents\/[^/]+$/) && method === 'DELETE') {
      const intentId = path.split('/').pop()!;
      intents = intents.filter((i) => i.id !== intentId);
      return route.fulfill({ status: 204 });
    }

    // ── Usage ──────────────────────────────────────
    if (path.match(/\/tenants\/[^/]+\/usage/)) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_USAGE),
      });
    }

    // ── Audit ──────────────────────────────────────
    if (path.match(/\/tenants\/[^/]+\/audit/)) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_AUDIT_LOGS),
      });
    }

    // ── Error simulation ──────────────────────────
    // POST to any /error-test path returns 500
    if (path.includes('/error-test') && method === 'POST') {
      return route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Internal server error (mock)' }),
      });
    }
    // GET to any /forbidden path returns 403
    if (path.includes('/forbidden')) {
      return route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Access denied (mock)' }),
      });
    }

    // ── Fallback ───────────────────────────────────
    return route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Not found (mock)' }),
    });
  });
}
