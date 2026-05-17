import { test, expect } from '@playwright/test';
import { injectAuth, mockTenantInfo, mockGet, MOCK_RULES, MOCK_USAGE, MOCK_AUDIT_LOGS } from './helpers';

test.describe('Dashboard Page', () => {
  test.beforeEach(async ({ page }) => {
    await injectAuth(page);
    await mockTenantInfo(page);
    await mockGet(page, '/rules', MOCK_RULES);
    await mockGet(page, '/usage', MOCK_USAGE);

    // Audit logs endpoint uses auditApi.list which hits /tenants/{tid}/audit
    await page.route('**/api/v1/tenants/test-tenant-id/audit*', (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(MOCK_AUDIT_LOGS),
        });
      }
      return route.continue();
    });
  });

  test('shows tenant name in heading', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: /test tenant overview/i })).toBeVisible();
  });

  test('displays four stat cards', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Total Requests')).toBeVisible();
    await expect(page.getByText('Total Tokens')).toBeVisible();
    await expect(page.getByText('Active Rules')).toBeVisible();
    await expect(page.getByText('Avg Latency')).toBeVisible();
  });

  test('stat card shows formatted request count', async ({ page }) => {
    await page.goto('/');
    // 12345 -> "12,345"
    await expect(page.getByText('12,345')).toBeVisible();
  });

  test('stat card shows formatted token count', async ({ page }) => {
    await page.goto('/');
    // 2_500_000 -> "2.5M"
    await expect(page.getByText('2.5M')).toBeVisible();
  });

  test('stat card shows active rules count', async ({ page }) => {
    await page.goto('/');
    // The "Active Rules" stat card contains the label and the count
    await expect(page.getByText('Active Rules')).toBeVisible();
    await expect(page.getByText('routing policies')).toBeVisible();
  });

  test('shows Request Volume chart section', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Request Volume')).toBeVisible();
    await expect(page.getByText('Live gateway traffic - last 7 days')).toBeVisible();
  });

  test('shows Model Distribution section', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Model Distribution')).toBeVisible();
    await expect(page.getByText('Token usage by model')).toBeVisible();
  });

  test('shows Recent Activity table with audit logs', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Recent Activity')).toBeVisible();
    // Recent Activity is a <ResponsiveTable> — column headers / row text
    // render in both the desktop <table> and the mobile card stack; only
    // one tree is visible per viewport, so scope to the visible match.
    await expect(page.getByText('Actor').locator('visible=true').first()).toBeVisible();
    await expect(page.getByText('Action').locator('visible=true').first()).toBeVisible();
    // Audit log action badges
    await expect(page.getByText('created_rule').locator('visible=true')).toBeVisible();
    await expect(page.getByText('deleted_model').locator('visible=true')).toBeVisible();
  });

  test('refresh button is visible and clickable', async ({ page }) => {
    await page.goto('/');
    const btn = page.getByRole('button', { name: /refresh/i });
    await expect(btn).toBeVisible();
    await btn.click();
    // Should re-render without error
    await expect(page.getByText('Total Requests')).toBeVisible();
  });

  test('shows empty state when no usage data', async ({ page }) => {
    // Override usage to return null-like data
    await mockGet(page, '/usage', { total_requests: 0, total_tokens: 0, by_model: {}, by_rule: {}, daily_breakdown: [] });
    await page.goto('/');
    await expect(page.getByText('No usage data yet')).toBeVisible();
  });
});
