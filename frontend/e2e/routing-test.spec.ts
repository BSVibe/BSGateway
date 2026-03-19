import { test, expect } from '@playwright/test';
import { setupAuth, setupApiMocks } from './fixtures/mock-api';

test.describe('Route Testing Page', () => {
  test.beforeEach(async ({ page }) => {
    await setupAuth(page);
    await setupApiMocks(page);
    await page.goto('/dashboard/test');
    await expect(page.locator('h2')).toContainText('Route Testing', { timeout: 5000 });
  });

  test('displays page header and subtitle', async ({ page }) => {
    await expect(page.locator('text=Test routing logic before deployment')).toBeVisible();
  });

  test('shows model dropdown populated from API', async ({ page }) => {
    const modelSelect = page.locator('select').first();
    await expect(modelSelect).toBeVisible();

    // Option text format is "model_name (provider)"
    const options = modelSelect.locator('option');
    // "Select model" placeholder + 3 mock models
    expect(await options.count()).toBeGreaterThanOrEqual(3);
    await expect(options.filter({ hasText: 'claude-sonnet' })).toBeAttached();
    await expect(options.filter({ hasText: 'gpt-4o' }).first()).toBeAttached();
  });

  test('shows message input area with role selector', async ({ page }) => {
    await expect(page.locator('label:has-text("Messages")')).toBeVisible();
    await expect(page.locator('textarea[placeholder="Message content"]')).toBeVisible();

    // Role selector defaults to "user"
    const roleSelect = page.locator('select').nth(1);
    await expect(roleSelect).toHaveValue('user');
  });

  test('can add and remove messages', async ({ page }) => {
    // Initially 1 message, no Remove button (single message)
    expect(await page.locator('textarea[placeholder="Message content"]').count()).toBe(1);

    // Add a second message
    await page.click('text=+ Add Message');
    expect(await page.locator('textarea[placeholder="Message content"]').count()).toBe(2);

    // Remove buttons appear for both messages when >1
    const removeButtons = page.locator('button:has-text("Remove")');
    expect(await removeButtons.count()).toBe(2);

    // Remove first message
    await removeButtons.first().click();
    expect(await page.locator('textarea[placeholder="Message content"]').count()).toBe(1);
  });

  test('can change message role', async ({ page }) => {
    const roleSelect = page.locator('select').nth(1);

    await roleSelect.selectOption('system');
    await expect(roleSelect).toHaveValue('system');

    await roleSelect.selectOption('assistant');
    await expect(roleSelect).toHaveValue('assistant');
  });

  test('runs a routing test and shows results', async ({ page }) => {
    // Model is preselected (first model)
    await page.fill('textarea[placeholder="Message content"]', 'This is urgent! Help me now.');

    await page.click('button:has-text("Test Routing")');

    // Results section
    await expect(page.locator('text=Test Result')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=Selected Model')).toBeVisible();
    await expect(page.locator('text=Matched Rule')).toBeVisible();
    await expect(page.locator('text=High-priority rule')).toBeVisible();
    await expect(page.locator('text=Latency')).toBeVisible();
    await expect(page.locator('text=4.2ms')).toBeVisible();
  });

  test('shows matched conditions in results', async ({ page }) => {
    await page.fill('textarea[placeholder="Message content"]', 'urgent request');
    await page.click('button:has-text("Test Routing")');

    await expect(page.locator('text=Matched Conditions')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=keyword:content:contains:urgent')).toBeVisible();
  });

  test('test button disabled when no model selected', async ({ page }) => {
    const modelSelect = page.locator('select').first();
    await modelSelect.selectOption('');

    const testBtn = page.locator('button:has-text("Test Routing")');
    await expect(testBtn).toBeDisabled();
  });
});
