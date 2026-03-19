import { test, expect } from '@playwright/test';
import { setupAuth, setupApiMocks } from './fixtures/mock-api';

test.describe('Audit Log Page', () => {
  test.beforeEach(async ({ page }) => {
    await setupAuth(page);
    await setupApiMocks(page);
    await page.goto('/dashboard/audit');
    await expect(page.locator('h2')).toContainText('Audit Log', { timeout: 5000 });
  });

  test('displays page header and subtitle', async ({ page }) => {
    await expect(page.locator('text=All admin operations and changes')).toBeVisible();
  });

  test('shows audit log table with headers', async ({ page }) => {
    await expect(page.locator('th:has-text("Timestamp")')).toBeVisible();
    await expect(page.locator('th:has-text("Actor")')).toBeVisible();
    await expect(page.locator('th:has-text("Action")')).toBeVisible();
    await expect(page.locator('th:has-text("Resource")')).toBeVisible();
  });

  test('shows audit log entries', async ({ page }) => {
    const rows = page.locator('tbody tr');
    expect(await rows.count()).toBe(3);
  });

  test('shows action badges with correct colors', async ({ page }) => {
    const createdBadge = page.locator('span:has-text("model.created")');
    await expect(createdBadge).toBeVisible();
    await expect(createdBadge).toHaveClass(/bg-green-100/);

    const deletedBadge = page.locator('span:has-text("model.deleted")');
    await expect(deletedBadge).toBeVisible();
    await expect(deletedBadge).toHaveClass(/bg-red-100/);

    const ruleCreatedBadge = page.locator('span:has-text("rule.created")');
    await expect(ruleCreatedBadge).toBeVisible();
    await expect(ruleCreatedBadge).toHaveClass(/bg-green-100/);
  });

  test('shows actor IDs truncated', async ({ page }) => {
    // All 3 rows have same actor - use first()
    await expect(page.locator('code:has-text("806c9083")').first()).toBeVisible();
  });

  test('shows resource types in resource column', async ({ page }) => {
    // Check resource types appear in the table
    const resourceCells = page.locator('tbody td:nth-child(4)');
    expect(await resourceCells.count()).toBe(3);

    // First row: "model: 806c9083-716"
    await expect(resourceCells.nth(0)).toContainText('model:');
    // Second row: "rule: r-001"
    await expect(resourceCells.nth(1)).toContainText('rule:');
    // Third row: "model: old-model-id"
    await expect(resourceCells.nth(2)).toContainText('model:');
  });

  test('shows formatted timestamps', async ({ page }) => {
    await expect(page.locator('td:has-text("Mar 19")').first()).toBeVisible();
  });
});
