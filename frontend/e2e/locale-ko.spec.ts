/**
 * Korean locale routing smoke test.
 *
 * With `localePrefix: 'as-needed'` and default `en`, the bare path serves
 * English (covered by every other spec) and `/ko` serves Korean. This
 * spec asserts the `/ko` prefix renders the Korean `gateway` catalog —
 * nav labels + the localized dashboard heading.
 */
import { test, expect } from '@playwright/test';
import { injectAuth, mockTenantInfo, mockGet, MOCK_RULES, MOCK_USAGE, MOCK_AUDIT_LOGS } from './helpers';

test.describe('Korean locale (/ko)', () => {
  test.beforeEach(async ({ page }) => {
    await injectAuth(page);
    await mockTenantInfo(page);
    await mockGet(page, '/rules', MOCK_RULES);
    await mockGet(page, '/usage', MOCK_USAGE);
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

  test('renders Korean nav labels under /ko', async ({ page }) => {
    await page.goto('/ko');
    // Korean nav label for "대시보드" (Dashboard) — proves the ko catalog loaded.
    await expect(page.getByRole('link', { name: '대시보드' })).toBeVisible();
    await expect(page.getByRole('link', { name: '라우팅' }).first()).toBeVisible();
  });

  test('renders the localized dashboard heading under /ko', async ({ page }) => {
    await page.goto('/ko');
    // dashboard.tenantOverview = "{tenant} 개요"
    await expect(page.getByRole('heading', { name: /개요/ })).toBeVisible();
  });

  test('sets <html lang="ko"> under /ko', async ({ page }) => {
    await page.goto('/ko');
    await expect(page.locator('html')).toHaveAttribute('lang', 'ko');
  });
});
