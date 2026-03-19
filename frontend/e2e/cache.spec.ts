import { test, expect } from '@playwright/test';
import { setupAuth, setupApiMocks } from './fixtures/mock-api';

test.describe('Cache Behavior', () => {
  test.beforeEach(async ({ page }) => {
    await setupAuth(page);
    await setupApiMocks(page);
  });

  test('rules page loads data and survives re-navigation', async ({ page }) => {
    await page.goto('/dashboard/rules');
    await expect(page.locator('h2')).toContainText('Routing Rules', { timeout: 5000 });
    await expect(page.locator('text=High-priority rule')).toBeVisible();

    // Navigate away and back
    await page.goto('/dashboard/');
    await expect(page.locator('h2:has-text("Dashboard")')).toBeVisible({ timeout: 5000 });

    await page.goto('/dashboard/rules');
    await expect(page.locator('text=High-priority rule')).toBeVisible();
  });

  test('models page loads data and survives re-navigation', async ({ page }) => {
    await page.goto('/dashboard/models');
    // Use main content h2, not sidebar
    await expect(page.locator('main h2, h2.text-2xl')).toContainText('Models', { timeout: 5000 });
    await expect(page.locator('.font-medium:has-text("claude-sonnet")')).toBeVisible();

    await page.goto('/dashboard/');
    await expect(page.locator('h2:has-text("Dashboard")')).toBeVisible({ timeout: 5000 });

    await page.goto('/dashboard/models');
    await expect(page.locator('.font-medium:has-text("claude-sonnet")')).toBeVisible();
  });

  test('creating a rule reflects immediately without reload', async ({ page }) => {
    await page.goto('/dashboard/rules');
    await expect(page.locator('h2')).toContainText('Routing Rules', { timeout: 5000 });

    await page.click('button:has-text("New Rule")');
    await page.locator('label:has-text("Name") + input').fill('Cache Test Rule');
    await page.locator('input[type="number"]').fill('999');
    await page.locator('label:has-text("Target Model") + input').fill('gpt-4o');
    await page.click('button:has-text("Create Rule")');

    await expect(page.locator('text=Cache Test Rule')).toBeVisible({ timeout: 5000 });
  });

  test('creating a model reflects immediately without reload', async ({ page }) => {
    await page.goto('/dashboard/models');
    await expect(page.locator('main h2, h2.text-2xl')).toContainText('Models', { timeout: 5000 });

    await page.click('button:has-text("Register Model")');
    await page.fill('input[placeholder="gpt-4o"]', 'cache-test-model');
    await page.fill('input[placeholder="openai/gpt-4o"]', 'openai/cache-test');
    await page.click('button:has-text("Register Model")');

    await expect(page.locator('text=cache-test-model')).toBeVisible({ timeout: 5000 });
  });
});
