import { test, expect } from '@playwright/test';
import { API_KEY, TENANT, setupApiMocks, setupAuth } from './fixtures/mock-api';

test.describe('Authentication Flow', () => {
  test.beforeEach(async ({ page }) => {
    await setupApiMocks(page);
  });

  test('shows login page when not authenticated', async ({ page }) => {
    await page.goto('/dashboard/');
    await expect(page.locator('h1')).toContainText('BSGateway');
    await expect(page.locator('text=LLM Routing Dashboard')).toBeVisible();
    await expect(page.locator('input[placeholder="bsg_..."]')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toContainText('Sign in');
  });

  test('login with valid API key redirects to dashboard', async ({ page }) => {
    await page.goto('/dashboard/');

    // Fill API key and submit
    await page.fill('input[placeholder="bsg_..."]', API_KEY);
    await page.click('button[type="submit"]');

    // Should render dashboard (authenticated layout)
    await expect(page.locator('h2')).toContainText('Dashboard', { timeout: 5000 });
    await expect(page.locator('text=Dev Team')).toBeVisible();

    // Token stored in sessionStorage
    const token = await page.evaluate(() => sessionStorage.getItem('bsg_token'));
    expect(token).toBeTruthy();
    expect(token).toMatch(/^eyJ/);
  });

  test('login with invalid API key shows error', async ({ page }) => {
    await page.goto('/dashboard/');

    await page.fill('input[placeholder="bsg_..."]', 'bsg_invalid-key');
    await page.click('button[type="submit"]');

    // Error message should appear
    await expect(page.locator('text=Invalid or expired')).toBeVisible({ timeout: 3000 });

    // Should still be on login page
    await expect(page.locator('button[type="submit"]')).toContainText('Sign in');
  });

  test('empty API key shows validation error', async ({ page }) => {
    await page.goto('/dashboard/');

    await page.click('button[type="submit"]');

    await expect(page.locator('text=API key is required')).toBeVisible();
  });

  test('API key show/hide toggle works', async ({ page }) => {
    await page.goto('/dashboard/');

    const input = page.locator('input[placeholder="bsg_..."]');
    await input.fill('test-secret-key');

    // Default is hidden - "Show" button visible
    await expect(page.locator('button:has-text("Show")')).toBeVisible();

    // Click show
    await page.click('button:has-text("Show")');
    await expect(page.locator('button:has-text("Hide")')).toBeVisible();

    // Click hide again
    await page.click('button:has-text("Hide")');
    await expect(page.locator('button:has-text("Show")')).toBeVisible();
  });

  test('auth token response contains correct tenant info', async ({ page }) => {
    await page.goto('/dashboard/');

    await page.fill('input[placeholder="bsg_..."]', API_KEY);

    // Intercept the auth response
    const responsePromise = page.waitForResponse('**/api/v1/auth/token');
    await page.click('button[type="submit"]');
    const response = await responsePromise;
    const data = await response.json();

    expect(data.token).toBeTruthy();
    expect(data.tenant_id).toBe(TENANT.id);
    expect(data.tenant_slug).toBe('dev-team');
    expect(data.tenant_name).toBe('Dev Team');
    expect(data.scopes).toContain('chat');
    expect(data.scopes).toContain('admin');
  });

  test('logout clears token and shows login', async ({ page }) => {
    // Start authenticated
    await setupAuth(page);
    await page.goto('/dashboard/');
    await expect(page.locator('h2')).toContainText('Dashboard', { timeout: 5000 });

    // Click logout
    await page.click('button:has-text("Logout")');

    // Should show login page
    await expect(page.locator('h1')).toContainText('BSGateway');
    await expect(page.locator('input[placeholder="bsg_..."]')).toBeVisible();

    // Token should be cleared
    const token = await page.evaluate(() => sessionStorage.getItem('bsg_token'));
    expect(token).toBeNull();
  });
});

test.describe('Dashboard Navigation (authenticated)', () => {
  test.beforeEach(async ({ page }) => {
    await setupAuth(page);
    await setupApiMocks(page);
    await page.goto('/dashboard/');
    await expect(page.locator('h2')).toContainText('Dashboard', { timeout: 5000 });
  });

  test('sidebar shows all nav items', async ({ page }) => {
    const navLabels = ['Dashboard', 'Rules', 'Models', 'Intents', 'Route Test', 'Usage', 'Audit Log'];
    for (const label of navLabels) {
      await expect(page.locator(`aside >> text=${label}`)).toBeVisible();
    }
  });

  test('can navigate to each page via sidebar', async ({ page }) => {
    // Rules
    await page.click('aside >> text=Rules');
    await expect(page.locator('h2')).toContainText('Routing Rules');

    // Models
    await page.click('aside >> text=Models');
    await expect(page.locator('h2')).toContainText('Models');

    // Intents
    await page.click('aside >> text=Intents');
    await expect(page.locator('h2')).toContainText('Custom Intents');

    // Route Test
    await page.click('aside >> text=Route Test');
    await expect(page.locator('h2')).toContainText('Route Testing');

    // Usage
    await page.click('aside >> text=Usage');
    await expect(page.locator('h2')).toContainText('Usage Analytics');

    // Audit Log
    await page.click('aside >> text=Audit Log');
    await expect(page.locator('h2')).toContainText('Audit Log');

    // Back to Dashboard
    await page.click('aside >> text=Dashboard');
    await expect(page.locator('h2')).toContainText('Dashboard');
  });

  test('sidebar shows tenant name and app title', async ({ page }) => {
    await expect(page.locator('aside >> text=BSGateway')).toBeVisible();
    await expect(page.locator('aside >> text=Dev Team')).toBeVisible();
  });
});
