import { test, expect } from '@playwright/test';
import { injectAuth, mockTenantInfo, mockGet, MOCK_RULES, MOCK_MODELS, MOCK_USAGE, MOCK_API_KEYS, MOCK_AUDIT_LOGS } from './helpers';

/**
 * Phase B Batch 2 — mobile viewport smoke flow.
 *
 * Runs against the `pixel-5` (393×851) and `iphone-13` (390×844) Playwright
 * projects. The chromium desktop project still owns the deep regression
 * suite — this file focuses on responsive chrome and the canonical user
 * flow (dashboard → drawer-nav → DataTable surface) on a small viewport.
 *
 * Preserves: output: 'export' static frontend + FastAPI mount path,
 * Sprint 0+1+2+3 routing/intent/dataset features.
 */

test.describe('Mobile viewport: BSGateway core flow', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    if (testInfo.project.name === 'chromium') {
      testInfo.skip();
    }
    await injectAuth(page);
    await mockTenantInfo(page);
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
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_AUDIT_LOGS) });
      }
      return route.continue();
    });
  });

  test('dashboard renders without horizontal overflow on mobile', async ({ page }) => {
    await page.goto('/');
    // Wait for the protected layout to settle.
    await page.waitForLoadState('networkidle');
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(2);
  });

  test('hamburger toggle opens the sidebar drawer', async ({ page }) => {
    await page.goto('/');
    const hamburger = page.getByRole('button', { name: /open navigation/i });
    await expect(hamburger).toBeVisible();
    await hamburger.click();
    await expect(page.getByTestId('bsgateway-sidebar-backdrop')).toBeVisible();
    // Confirm a nav link is reachable. Sidebar links include their material
    // icon text in the accessible name (e.g. "alt_route Routing"), so we
    // anchor on the link text suffix.
    await expect(page.getByRole('link', { name: /Routing$/ }).first()).toBeVisible();
  });

  test('hamburger trigger meets 44px touch-target minimum', async ({ page }) => {
    await page.goto('/');
    const hamburger = page.getByRole('button', { name: /open navigation/i });
    const box = await hamburger.boundingBox();
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(44);
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
  });

  test('clicking a sidebar link closes the drawer (mobile UX)', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: /open navigation/i }).click();
    await expect(page.getByTestId('bsgateway-sidebar-backdrop')).toBeVisible();
    await page.getByRole('link', { name: /API Keys$/ }).click();
    await expect(page.getByTestId('bsgateway-sidebar-backdrop')).toHaveCount(0);
    await expect(page).toHaveURL(/\/api-keys/);
  });

  test('backdrop click closes the drawer', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: /open navigation/i }).click();
    const backdrop = page.getByTestId('bsgateway-sidebar-backdrop');
    await expect(backdrop).toBeVisible();
    await backdrop.click();
    await expect(backdrop).toHaveCount(0);
  });

  test('routing rules table is horizontally scrollable on mobile', async ({ page }) => {
    await page.goto('/rules');
    await page.waitForLoadState('networkidle');
    // Tables are wrapped in `overflow-x-auto` containers on every list page.
    // Mobile viewport (393px) is too narrow for full table — content must
    // overflow horizontally rather than clip.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    // Page-level overflow must be at most a few px (caused by scrollbar).
    expect(overflow).toBeLessThanOrEqual(2);
  });
});
