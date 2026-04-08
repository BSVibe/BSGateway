import { test, expect } from '@playwright/test';
import { injectAuth, mockTenantInfo, mockGet, MOCK_API_KEYS, MOCK_RULES } from './helpers';

/**
 * Navigate to /api-keys via SPA routing (not direct URL).
 * Direct goto('/api-keys') is intercepted by Vite's '/api' proxy rule,
 * so we load the root first then use client-side navigation.
 */
async function gotoApiKeys(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.evaluate(() => window.history.pushState({}, '', '/api-keys'));
  await page.goto('/api-keys', { waitUntil: 'commit' }).catch(() => {});
  // Use SPA routing by navigating from root
  await page.goto('/');
  await page.locator('aside').getByText('API Keys').click();
  await page.waitForURL('**/api-keys');
}

test.describe('API Keys Page', () => {
  test.beforeEach(async ({ page }) => {
    await injectAuth(page);
    await mockTenantInfo(page);
    await mockGet(page, '/api-keys', MOCK_API_KEYS);
    // Dashboard requires these mocks when loading root page first
    await mockGet(page, '/rules', MOCK_RULES);
    await mockGet(page, '/usage', { total_requests: 0, total_tokens: 0, by_model: {}, by_rule: {}, daily_breakdown: [] });
    await page.route('**/api/v1/tenants/test-tenant-id/audit*', (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
      }
      return route.continue();
    });
  });

  test('displays page heading', async ({ page }) => {
    await gotoApiKeys(page);
    await expect(page.getByRole('heading', { name: /api keys/i })).toBeVisible();
    await expect(page.getByText('Manage access keys for your applications.')).toBeVisible();
  });

  test('shows summary cards with correct counts', async ({ page }) => {
    await gotoApiKeys(page);
    // Active Keys: 2 (production + staging)
    const activeCard = page.locator('div').filter({ hasText: /^Active Keys/ });
    await expect(activeCard.getByText('2')).toBeVisible();
    // Total Keys: 3
    const totalCard = page.locator('div').filter({ hasText: /^Total Keys/ });
    await expect(totalCard.getByText('3')).toBeVisible();
    // Revoked: 1
    const revokedCard = page.locator('div').filter({ hasText: /^Revoked/ });
    await expect(revokedCard.getByText('1')).toBeVisible();
  });

  test('shows keys table with correct columns', async ({ page }) => {
    await gotoApiKeys(page);
    await expect(page.getByText('Name', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('Key', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('Created', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('Last Used', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('Status', { exact: true }).first()).toBeVisible();
  });

  test('renders key rows with names and prefixes', async ({ page }) => {
    await gotoApiKeys(page);
    await expect(page.getByText('production')).toBeVisible();
    await expect(page.getByText('staging')).toBeVisible();
    await expect(page.getByText('revoked-key')).toBeVisible();
    // Key prefixes
    await expect(page.getByText('bsg_prod_abc...')).toBeVisible();
  });

  test('shows Active and Revoked status badges', async ({ page }) => {
    await gotoApiKeys(page);
    const activeBadges = page.getByText('Active', { exact: true });
    await expect(activeBadges.first()).toBeVisible();
    await expect(page.getByRole('table').getByText('Revoked', { exact: true })).toBeVisible();
  });

  test('shows "Never" for keys without last_used_at', async ({ page }) => {
    await gotoApiKeys(page);
    await expect(page.getByText('Never')).toBeVisible();
  });

  test('Generate New Key button toggles form', async ({ page }) => {
    await gotoApiKeys(page);
    const btn = page.getByRole('button', { name: /generate new key/i });
    await expect(btn).toBeVisible();
    await btn.click();
    await expect(page.getByPlaceholder(/production, staging, ci-pipeline/i)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Create Key' })).toBeVisible();
  });

  test('Create Key button disabled without name', async ({ page }) => {
    await gotoApiKeys(page);
    await page.getByRole('button', { name: /generate new key/i }).click();
    await expect(page.getByRole('button', { name: 'Create Key' })).toBeDisabled();
  });

  test('shows new key banner after creation', async ({ page }) => {
    // Unroute existing handler and replace with one that handles both GET and POST
    await page.unroute('**/api/v1/tenants/test-tenant-id/api-keys*');
    await page.route('**/api/v1/tenants/test-tenant-id/api-keys*', (route) => {
      if (route.request().method() === 'POST') {
        return route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 'new-key-1',
            tenant_id: 'test-tenant-id',
            name: 'new-key',
            key_prefix: 'bsg_new_abc',
            raw_key: 'bsg_new_abcdef123456789',
            scopes: ['*'],
            created_at: '2026-03-29T12:00:00Z',
          }),
        });
      }
      // GET: return the mock keys list
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_API_KEYS),
      });
    });

    await gotoApiKeys(page);
    await page.getByRole('button', { name: /generate new key/i }).click();
    await page.getByPlaceholder(/production, staging, ci-pipeline/i).fill('new-key');
    await page.getByRole('button', { name: 'Create Key' }).click();

    await expect(page.getByText(/copy it now/i)).toBeVisible();
    await expect(page.getByText('bsg_new_abcdef123456789')).toBeVisible();
  });

  test('shows security documentation section', async ({ page }) => {
    await gotoApiKeys(page);
    await expect(page.getByText('Secure your API implementation')).toBeVisible();
  });

  test('empty state when no keys exist', async ({ page }) => {
    await mockGet(page, '/api-keys', []);
    await gotoApiKeys(page);
    await expect(page.getByText('No API keys created')).toBeVisible();
  });
});
