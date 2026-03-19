import { test, expect } from '@playwright/test';
import { setupAuth, setupApiMocks, MOCK_USAGE } from './fixtures/mock-api';

test.describe('Usage Analytics Page', () => {
  test.beforeEach(async ({ page }) => {
    await setupAuth(page);
    await setupApiMocks(page);
    await page.goto('/dashboard/usage');
    await expect(page.locator('h2')).toContainText('Usage Analytics', { timeout: 5000 });
  });

  test('displays page header and subtitle', async ({ page }) => {
    await expect(page.locator('text=Routing traffic and token consumption')).toBeVisible();
  });

  test('shows period selector defaulting to week', async ({ page }) => {
    const select = page.locator('select');
    await expect(select).toHaveValue('week');

    // All period options available
    await expect(page.locator('option[value="day"]')).toBeAttached();
    await expect(page.locator('option[value="week"]')).toBeAttached();
    await expect(page.locator('option[value="month"]')).toBeAttached();
  });

  test('shows summary stats cards', async ({ page }) => {
    // Total Requests
    await expect(page.locator('text=Total Requests')).toBeVisible();
    await expect(page.locator(`text=${MOCK_USAGE.total_requests}`)).toBeVisible();

    // Total Tokens
    await expect(page.locator('text=Total Tokens')).toBeVisible();
    await expect(page.locator('text=523,800')).toBeVisible();

    // Success Rate
    await expect(page.locator('text=Success Rate')).toBeVisible();
    await expect(page.locator('text=99%')).toBeVisible();
  });

  test('shows daily requests chart', async ({ page }) => {
    await expect(page.locator('text=Daily Requests')).toBeVisible();
    // Recharts renders SVG
    await expect(page.locator('.recharts-responsive-container').first()).toBeVisible();
  });

  test('shows traffic by model chart', async ({ page }) => {
    await expect(page.locator('text=Traffic by Model')).toBeVisible();
  });

  test('shows traffic by rule chart', async ({ page }) => {
    await expect(page.locator('text=Traffic by Rule')).toBeVisible();
  });

  test('can switch period to day', async ({ page }) => {
    const select = page.locator('select');
    await select.selectOption('day');
    await expect(select).toHaveValue('day');

    // Should still show stats after reload
    await expect(page.locator('text=Total Requests')).toBeVisible({ timeout: 5000 });
  });

  test('can switch period to month', async ({ page }) => {
    const select = page.locator('select');
    await select.selectOption('month');
    await expect(select).toHaveValue('month');

    await expect(page.locator('text=Total Requests')).toBeVisible({ timeout: 5000 });
  });
});
