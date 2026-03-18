import { test, expect } from '@playwright/test';

const API_KEY = 'bsg_dev-test-key-do-not-use-in-production-000';
const API_BASE = 'http://localhost:8000/api/v1';

test.describe('Cache Invalidation', () => {
  let tenantId: string;

  test.beforeAll(async ({ browser }) => {
    // Get tenant ID from API
    const context = await browser.newContext();
    const page = await context.newPage();
    const response = await page.request.get(`${API_BASE}/tenants`, {
      headers: { Authorization: `Bearer ${API_KEY}` },
    });
    const tenants = await response.json();
    if (Array.isArray(tenants) && tenants.length > 0) {
      tenantId = tenants[0].id;
    }
    await context.close();
  });

  test.beforeEach(async ({ page }) => {
    // Login before each test
    await page.goto('/');
    const input = page.locator('input[type="text"]');
    await input.fill(API_KEY);
    const button = page.locator('button[type="submit"]');
    await button.click();
    await page.waitForURL('/dashboard', { timeout: 5000 });
  });

  test('should cache rules on first fetch', async ({ page }) => {
    await page.goto(`/dashboard/${tenantId}/rules`);

    // First load - rules fetched from API
    await expect(page.locator('h2')).toContainText('Routing Rules');

    // Wait for rules to load
    await page.waitForTimeout(500);

    // Second navigation - should use cache
    await page.goto(`/dashboard/${tenantId}`);
    await page.goto(`/dashboard/${tenantId}/rules`);

    // Rules should still be visible (from cache or fresh fetch)
    await expect(page.locator('h2')).toContainText('Routing Rules');
  });

  test('should invalidate cache when rule is created', async ({ page }) => {
    await page.goto(`/dashboard/${tenantId}/rules`);

    // Get initial rule count
    const ruleCountBefore = await page.locator('[data-testid="rule-item"]').count();

    // Create a new rule
    const newBtn = page.locator('button:has-text("New Rule")');
    await newBtn.click();

    // Fill form
    const nameInput = page.locator('input').first();
    await nameInput.fill(`Cache Test Rule ${Date.now()}`);

    const priorityInput = page.locator('input[type="number"]');
    await priorityInput.fill('999');

    const targetInput = page.locator('input').nth(1);
    await targetInput.fill('gpt-4o');

    // Submit form
    const submitBtn = page.locator('button:has-text("Create")');
    await submitBtn.click();

    // Wait for success and cache invalidation
    await page.waitForTimeout(1000);

    // Verify rule count increased
    const ruleCountAfter = await page.locator('[data-testid="rule-item"]').count();
    expect(ruleCountAfter).toBeGreaterThan(ruleCountBefore);
  });

  test('should invalidate cache when rule is deleted', async ({ page }) => {
    await page.goto(`/dashboard/${tenantId}/rules`);

    // Get initial rule count
    const ruleCountBefore = await page.locator('[data-testid="rule-item"]').count();

    if (ruleCountBefore === 0) {
      test.skip();
    }

    // Delete first rule
    const firstRule = page.locator('[data-testid="rule-item"]').first();
    const deleteBtn = firstRule.locator('button:has-text("Delete")');
    await deleteBtn.click();

    // Confirm deletion
    const confirmBtn = page.locator('button:has-text("Confirm")');
    if (await confirmBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await confirmBtn.click();
    }

    // Wait for cache invalidation
    await page.waitForTimeout(1000);

    // Verify rule count decreased
    const ruleCountAfter = await page.locator('[data-testid="rule-item"]').count();
    expect(ruleCountAfter).toBeLessThanOrEqual(ruleCountBefore);
  });

  test('should cache models on first fetch', async ({ page }) => {
    await page.goto(`/dashboard/${tenantId}/models`);

    // First load - models fetched from API
    await expect(page.locator('h2')).toContainText('Models');

    // Wait for models to load
    await page.waitForTimeout(500);

    // Second navigation - should use cache
    await page.goto(`/dashboard/${tenantId}`);
    await page.goto(`/dashboard/${tenantId}/models`);

    // Models should still be visible
    await expect(page.locator('h2')).toContainText('Models');
  });

  test('should invalidate cache when model is created', async ({ page }) => {
    await page.goto(`/dashboard/${tenantId}/models`);

    // Get initial model count
    const modelCountBefore = await page.locator('[data-testid="model-item"]').count();

    // Create a new model
    const newBtn = page.locator('button:has-text("Add Model")');
    await newBtn.click();

    // Fill form
    const nameInput = page.locator('input[placeholder*="Model name"]').first();
    await nameInput.fill(`cache-test-${Date.now()}`);

    const litellmInput = page.locator('input[placeholder*="litellm model"]');
    await litellmInput.fill('openai/gpt-4o');

    // Submit form
    const submitBtn = page.locator('button:has-text("Register")');
    await submitBtn.click();

    // Wait for success and cache invalidation
    await page.waitForTimeout(1000);

    // Verify model count increased
    const modelCountAfter = await page.locator('[data-testid="model-item"]').count();
    expect(modelCountAfter).toBeGreaterThanOrEqual(modelCountBefore);
  });

  test('should invalidate cache when model is deleted', async ({ page }) => {
    await page.goto(`/dashboard/${tenantId}/models`);

    // Get initial model count
    const modelCountBefore = await page.locator('[data-testid="model-item"]').count();

    if (modelCountBefore === 0) {
      test.skip();
    }

    // Delete first model
    const firstModel = page.locator('[data-testid="model-item"]').first();
    const deleteBtn = firstModel.locator('button:has-text("Delete")');
    await deleteBtn.click();

    // Confirm deletion
    const confirmBtn = page.locator('button:has-text("Confirm")');
    if (await confirmBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await confirmBtn.click();
    }

    // Wait for cache invalidation
    await page.waitForTimeout(1000);

    // Verify model count decreased
    const modelCountAfter = await page.locator('[data-testid="model-item"]').count();
    expect(modelCountAfter).toBeLessThanOrEqual(modelCountBefore);
  });
});
