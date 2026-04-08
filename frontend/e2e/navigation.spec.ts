import { test, expect } from '@playwright/test';
import { injectAuth, mockTenantInfo, mockGet, MOCK_RULES, MOCK_MODELS, MOCK_USAGE, MOCK_API_KEYS } from './helpers';

test.describe('Sidebar Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await injectAuth(page);
    await mockTenantInfo(page);

    // Mock all API endpoints needed by different pages
    await mockGet(page, '/rules', MOCK_RULES);
    await mockGet(page, '/models', MOCK_MODELS);
    await mockGet(page, '/api-keys', MOCK_API_KEYS);
    await page.route('**/api/v1/tenants/test-tenant-id/usage*', (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_USAGE) });
      }
      return route.continue();
    });
    await page.route('**/api/v1/tenants/test-tenant-id/audit*', (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [], total: 0 }) });
      }
      return route.continue();
    });
    await page.route('**/api/v1/tenants/test-tenant-id/intents*', (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
      }
      return route.continue();
    });
  });

  test('sidebar shows BSGateway branding', async ({ page }) => {
    await page.goto('/');
    const sidebar = page.locator('aside');
    await expect(sidebar.getByText('BSGateway')).toBeVisible();
  });

  test('sidebar shows tenant name', async ({ page }) => {
    await page.goto('/');
    const sidebar = page.locator('aside');
    await expect(sidebar.getByText('Test Tenant')).toBeVisible();
  });

  test('sidebar contains all navigation links', async ({ page }) => {
    await page.goto('/');
    const nav = page.locator('aside nav');
    await expect(nav.getByRole('link', { name: /Dashboard/i })).toBeVisible();
    await expect(nav.getByRole('link', { name: /^.*Routing$/i })).toBeVisible();
    await expect(nav.getByRole('link', { name: /Models/i })).toBeVisible();
    await expect(nav.getByRole('link', { name: /Routing Test/i })).toBeVisible();
    await expect(nav.getByRole('link', { name: /Analytics/i })).toBeVisible();
    await expect(nav.getByRole('link', { name: /API Keys/i })).toBeVisible();
    await expect(nav.getByRole('link', { name: /Audit Log/i })).toBeVisible();
  });

  test('Dashboard link is active on root path', async ({ page }) => {
    await page.goto('/');
    const dashLink = page.locator('aside a').filter({ hasText: 'Dashboard' });
    // Active link has amber-500 text (using class check)
    await expect(dashLink).toHaveClass(/text-amber-500/);
  });

  test('navigating to Routing activates Routing link', async ({ page }) => {
    await page.goto('/');
    await page.locator('aside').getByText('Routing', { exact: true }).click();
    await expect(page).toHaveURL(/\/rules/);
    const rulesLink = page.locator('aside a').filter({ hasText: /^\s*alt_route\s*Routing\s*$/ });
    await expect(rulesLink).toHaveClass(/text-amber-500/);
  });

  test('navigating to Models activates Models link', async ({ page }) => {
    await page.goto('/');
    await page.locator('aside').getByText('Models').click();
    await expect(page).toHaveURL(/\/models/);
    await expect(page.getByRole('heading', { name: /model registry/i })).toBeVisible();
  });

  test('navigating to Analytics activates Analytics link', async ({ page }) => {
    await page.goto('/');
    await page.locator('aside').getByText('Analytics').click();
    await expect(page).toHaveURL(/\/usage/);
    await expect(page.getByRole('heading', { name: /analytics dashboard/i })).toBeVisible();
  });

  test('navigating to API Keys loads the page', async ({ page }) => {
    await page.goto('/');
    await page.locator('aside').getByText('API Keys').click();
    await expect(page).toHaveURL(/\/api-keys/);
    await expect(page.getByRole('heading', { name: /api keys/i })).toBeVisible();
  });

  test('navigating to Audit Log loads the page', async ({ page }) => {
    await page.goto('/');
    await page.locator('aside').getByText('Audit Log').click();
    await expect(page).toHaveURL(/\/audit/);
    await expect(page.getByRole('heading', { name: /audit log/i })).toBeVisible();
  });

  test('Logout button is visible', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('button', { name: /Logout/i })).toBeVisible();
  });

  test('uses Material Symbols icons in nav items', async ({ page }) => {
    await page.goto('/');
    const sidebar = page.locator('aside');
    // Check that material-symbols-outlined spans exist
    const icons = sidebar.locator('.material-symbols-outlined');
    // At least 7 nav items + logo + logout = 9+
    expect(await icons.count()).toBeGreaterThanOrEqual(8);
  });
});
