import { test, expect } from '@playwright/test';
import { setupAuth, setupApiMocks, MOCK_RULES, MOCK_MODELS, MOCK_USAGE } from './fixtures/mock-api';

test.describe('Dashboard Page', () => {
  test.beforeEach(async ({ page }) => {
    await setupAuth(page);
    await setupApiMocks(page);
    await page.goto('/dashboard/');
    await expect(page.locator('h2')).toContainText('Dashboard', { timeout: 5000 });
  });

  test('displays page header and subtitle', async ({ page }) => {
    await expect(page.locator('text=Routing overview and metrics')).toBeVisible();
  });

  test('shows stats cards with correct data', async ({ page }) => {
    await expect(page.locator('text=Active Rules')).toBeVisible();
    await expect(page.locator(`text=${MOCK_RULES.length}`).first()).toBeVisible();

    await expect(page.locator('text=Registered Models')).toBeVisible();
    await expect(page.locator(`text=${MOCK_MODELS.length}`).first()).toBeVisible();

    await expect(page.locator('text=Daily Requests')).toBeVisible();
    await expect(page.locator(`text=${MOCK_USAGE.total_requests}`)).toBeVisible();

    await expect(page.locator('text=Success Rate')).toBeVisible();
    await expect(page.locator('text=99%')).toBeVisible();
  });

  test('shows usage trend chart', async ({ page }) => {
    await expect(page.locator('text=Request Trend (7 days)')).toBeVisible();
    await expect(page.locator('.recharts-responsive-container')).toBeVisible();
  });

  test('shows getting started guide', async ({ page }) => {
    await expect(page.locator('text=Getting Started')).toBeVisible();
    await expect(page.locator('text=Register your LLM models')).toBeVisible();
  });

  test('shows API integration info', async ({ page }) => {
    // Section may be below fold, scroll to it
    const apiSection = page.locator('text=API Integration');
    await apiSection.scrollIntoViewIfNeeded();
    await expect(apiSection).toBeVisible();

    // The endpoint is inside a <code> element
    await expect(page.locator('code:has-text("chat/completions")')).toBeVisible();
  });
});
