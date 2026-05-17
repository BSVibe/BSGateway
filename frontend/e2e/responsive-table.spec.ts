import { test, expect } from '@playwright/test';
import {
  injectAuth,
  mockTenantInfo,
  mockGet,
  MOCK_RULES,
  MOCK_INTENTS,
  MOCK_EXAMPLES,
  MOCK_MODELS,
  MOCK_USAGE,
  MOCK_AUDIT_LOGS,
} from './helpers';

/**
 * ResponsiveTable adoption coverage.
 *
 * The audit / dashboard / routes / models views now render the shared
 * @bsvibe/ui <ResponsiveTable>, which dual-renders:
 *   - a `<table>` (inside data-testid="bsvibe-table-scroll") at the sm:
 *     breakpoint and up — visible on the desktop `chromium` project, and
 *   - a card stack (data-testid="bsvibe-table-mobile") below sm: — visible
 *     on the `pixel-5` / `iphone-13` mobile projects.
 *
 * On desktop the `<table>` must be visible; on mobile it must be hidden and
 * the card stack visible. Views that pass `renderMobileCard` (routes, models)
 * keep their bespoke card markup, so they are asserted via the
 * `bsvibe-table-mobile` container rather than the default `bsvibe-table-card`.
 */

const isMobile = (name: string) => name === 'pixel-5' || name === 'iphone-13';

test.describe('ResponsiveTable adoption', () => {
  test.beforeEach(async ({ page }) => {
    await injectAuth(page);
    await mockTenantInfo(page);
    await mockGet(page, '/rules', MOCK_RULES);
    await mockGet(page, '/intents', MOCK_INTENTS);
    await mockGet(page, '/intents/intent-1/examples', MOCK_EXAMPLES);
    await mockGet(page, '/models', MOCK_MODELS);
    await mockGet(page, '/embedding-settings', null);
    await page.route('**/api/v1/tenants/test-tenant-id/usage*', (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(MOCK_USAGE),
        });
      }
      return route.continue();
    });
  });

  /**
   * The /audit endpoint is consumed two ways: AuditPage expects the
   * {items, total} envelope, while DashboardPage's auditApi.list expects a
   * bare array. Each test mocks the shape its page needs.
   */
  const mockAuditEnvelope = (page: import('@playwright/test').Page, body: unknown) =>
    page.route('**/api/v1/tenants/test-tenant-id/audit*', (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(body),
        });
      }
      return route.continue();
    });

  // ---- Audit ----

  test('audit log dual-renders table on desktop / cards on mobile', async ({ page }, testInfo) => {
    await mockAuditEnvelope(page, { items: MOCK_AUDIT_LOGS, total: MOCK_AUDIT_LOGS.length });
    await page.goto('/audit');
    await expect(page.getByRole('heading', { name: /audit log/i })).toBeVisible();

    const table = page.locator('[data-testid="bsvibe-table-scroll"] table');
    const cards = page.locator('[data-testid="bsvibe-table-card"]');

    if (isMobile(testInfo.project.name)) {
      await expect(table).toBeHidden();
      await expect(cards.first()).toBeVisible();
      await expect(cards).toHaveCount(MOCK_AUDIT_LOGS.length);
    } else {
      await expect(table).toBeVisible();
      // 2 audit log rows
      await expect(table.locator('tbody tr')).toHaveCount(MOCK_AUDIT_LOGS.length);
      await expect(table.getByText('created_rule')).toBeVisible();
    }
  });

  test('audit empty state renders the bsvibe-table-empty marker', async ({ page }) => {
    await mockAuditEnvelope(page, { items: [], total: 0 });
    await page.goto('/audit');
    await expect(page.locator('[data-testid="bsvibe-table-empty"]')).toBeVisible();
    await expect(page.getByText('No audit logs')).toBeVisible();
  });

  // ---- Dashboard ----

  test('dashboard Recent Activity dual-renders table / cards', async ({ page }, testInfo) => {
    // DashboardPage's auditApi.list expects a bare array.
    await mockAuditEnvelope(page, MOCK_AUDIT_LOGS);
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Recent Activity' })).toBeVisible();

    const table = page.locator('[data-testid="bsvibe-table-scroll"] table');
    const cards = page.locator('[data-testid="bsvibe-table-card"]');

    if (isMobile(testInfo.project.name)) {
      await expect(table).toBeHidden();
      await expect(cards.first()).toBeVisible();
    } else {
      await expect(table).toBeVisible();
      await expect(table.getByText('created_rule')).toBeVisible();
      await expect(table.getByText('deleted_model')).toBeVisible();
    }
  });

  // ---- Routes (renderMobileCard — keeps RouteCard markup on mobile) ----

  test('routes dual-renders table on desktop / RouteCard stack on mobile', async ({ page }, testInfo) => {
    await page.goto('/rules');
    await expect(page.getByRole('heading', { name: /routing rules/i })).toBeVisible();
    // Route description appears in both trees — assert the visible one.
    await expect(
      page.getByText('Code review and debugging requests').locator('visible=true'),
    ).toBeVisible();

    const table = page.locator('[data-testid="bsvibe-table-scroll"] table');
    const mobileStack = page.locator('[data-testid="bsvibe-table-mobile"]');

    if (isMobile(testInfo.project.name)) {
      await expect(table).toBeHidden();
      await expect(mobileStack).toBeVisible();
    } else {
      await expect(table).toBeVisible();
      // Priority badge survives the table conversion.
      await expect(table.getByText('P0')).toBeVisible();
      await expect(table.getByText('2 examples')).toBeVisible();
    }
  });

  test('routes desktop table keeps the expandable examples panel', async ({ page }, testInfo) => {
    testInfo.skip(isMobile(testInfo.project.name), 'desktop-only assertion');
    await page.goto('/rules');
    // "2 examples" exists in both trees — click the visible (desktop) one.
    await page.getByText('2 examples').locator('visible=true').click();
    await expect(page.getByText('Example phrases').locator('visible=true')).toBeVisible();
    await expect(page.getByText('Please review this code').locator('visible=true')).toBeVisible();
  });

  // ---- Models (renderMobileCard — keeps model/worker cards on mobile) ----

  test('models dual-renders table on desktop / card stack on mobile', async ({ page }, testInfo) => {
    await page.goto('/models');
    await expect(page.getByRole('heading', { name: /model registry/i })).toBeVisible();

    const table = page.locator('[data-testid="bsvibe-table-scroll"] table');
    const mobileStack = page.locator('[data-testid="bsvibe-table-mobile"]');

    if (isMobile(testInfo.project.name)) {
      await expect(table.first()).toBeHidden();
      await expect(mobileStack.first()).toBeVisible();
    } else {
      await expect(table.first()).toBeVisible();
      // 3 LLM models from MOCK_MODELS.
      await expect(table.first().locator('tbody tr')).toHaveCount(MOCK_MODELS.length);
      // First row, first cell = model name.
      await expect(table.first().locator('tbody tr').first().locator('td').first()).toContainText(
        'gpt-4o',
      );
    }
  });

  test('models empty state renders the bsvibe-table-empty marker on neither — custom empty kept', async ({ page }) => {
    await mockGet(page, '/models', []);
    await page.goto('/models');
    // ModelsPage keeps its bespoke empty state outside ResponsiveTable.
    await expect(page.getByText('No models registered')).toBeVisible();
  });
});
