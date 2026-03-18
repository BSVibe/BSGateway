import { test, expect } from '@playwright/test';

const API_KEY = 'bsg_dev-test-key-do-not-use-in-production-000';

test.describe('Authentication', () => {
  test('should login with API key', async ({ page }) => {
    await page.goto('/');

    // Should be on login page
    await expect(page).toHaveTitle(/BSGateway/);

    // Enter API key
    const input = page.locator('input[type="text"]');
    await input.fill(API_KEY);

    // Submit
    const button = page.locator('button[type="submit"]');
    await button.click();

    // Should redirect to dashboard
    await page.waitForURL('/dashboard', { timeout: 5000 });
    await expect(page.locator('h2')).toContainText('Dashboard');
  });

  test('should show error for invalid API key', async ({ page }) => {
    await page.goto('/');

    const input = page.locator('input[type="text"]');
    await input.fill('invalid-key');

    const button = page.locator('button[type="submit"]');
    await button.click();

    // Should show error message
    const error = page.locator('text=Invalid or expired API key');
    await expect(error).toBeVisible({ timeout: 5000 });
  });

  test('should logout', async ({ page }) => {
    await page.goto('/');

    // Login
    const input = page.locator('input[type="text"]');
    await input.fill(API_KEY);
    const button = page.locator('button[type="submit"]');
    await button.click();

    // Wait for dashboard
    await page.waitForURL('/dashboard', { timeout: 5000 });

    // Click logout
    const logoutBtn = page.locator('button:has-text("Logout")');
    await logoutBtn.click();

    // Should be back on login page
    await page.waitForURL('/login', { timeout: 5000 });
    await expect(page.locator('h1')).toContainText('BSGateway');
  });
});
