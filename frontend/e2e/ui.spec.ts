import { test, expect } from '@playwright/test';
import { setupApiMocks, setupAuth } from './fixtures/mock-api';

test.describe('Login Page UI', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/dashboard/');
    await page.waitForLoadState('networkidle');
  });

  test('renders app title and subtitle', async ({ page }) => {
    await expect(page.locator('h1')).toContainText('BSGateway');
    await expect(page.locator('text=LLM Routing Dashboard')).toBeVisible();
  });

  test('renders API key input field', async ({ page }) => {
    const input = page.locator('input[placeholder="bsg_..."]');
    await expect(input).toBeVisible();

    await input.fill('test-api-key');
    await expect(input).toHaveValue('test-api-key');
  });

  test('renders submit button', async ({ page }) => {
    const button = page.locator('button[type="submit"]');
    await expect(button).toBeVisible();
    await expect(button).toContainText('Sign in');
  });

  test('shows helper text', async ({ page }) => {
    await expect(page.locator('text=Your API key identifies the tenant automatically')).toBeVisible();
  });

  test('renders label for API key', async ({ page }) => {
    await expect(page.locator('label:has-text("API Key")')).toBeVisible();
  });
});

test.describe('Responsive Layout', () => {
  test('login page works on mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/dashboard/');
    await page.waitForLoadState('networkidle');

    await expect(page.locator('input[placeholder="bsg_..."]')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toBeVisible();
  });

  test('login page works on tablet viewport', async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.goto('/dashboard/');
    await page.waitForLoadState('networkidle');

    await expect(page.locator('input[placeholder="bsg_..."]')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toBeVisible();
  });

  test('dashboard layout has sidebar on desktop', async ({ page }) => {
    await setupAuth(page);
    await setupApiMocks(page);
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/dashboard/');
    await expect(page.locator('aside')).toBeVisible();
    await expect(page.locator('h2:has-text("Dashboard")')).toBeVisible({ timeout: 5000 });
  });
});

test.describe('Performance', () => {
  test('login page loads within 5 seconds', async ({ page }) => {
    const start = Date.now();
    await page.goto('/dashboard/');
    await page.waitForLoadState('networkidle');
    expect(Date.now() - start).toBeLessThan(5000);
  });

  test('no console errors on login page', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        errors.push(msg.text());
      }
    });

    await page.goto('/dashboard/');
    await page.waitForLoadState('networkidle');

    expect(errors).toHaveLength(0);
  });

  test('no blocking network errors on login page', async ({ page }) => {
    const networkErrors: string[] = [];
    page.on('response', (response) => {
      if (!response.ok() && response.status() >= 400) {
        networkErrors.push(`${response.status()} ${response.url()}`);
      }
    });

    await page.goto('/dashboard/');
    await page.waitForLoadState('networkidle');

    // Allow API 404s (no backend), only check for non-API errors
    const blockingErrors = networkErrors.filter((err) => !err.includes('/api'));
    expect(blockingErrors).toHaveLength(0);
  });
});
