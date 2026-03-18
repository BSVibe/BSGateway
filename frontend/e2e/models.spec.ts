import { test, expect } from '@playwright/test';

const API_KEY = 'bsg_dev-test-key-do-not-use-in-production-000';

test.describe('Models Management', () => {
  test.beforeEach(async ({ page }) => {
    // Login before each test
    await page.goto('/');
    const input = page.locator('input[type="text"]');
    await input.fill(API_KEY);
    const button = page.locator('button[type="submit"]');
    await button.click();
    await page.waitForURL('/dashboard', { timeout: 5000 });
  });

  test('should navigate to Models page', async ({ page }) => {
    await page.goto('/dashboard/models');
    await expect(page.locator('h2')).toContainText('Models');
  });

  test('should open register model form', async ({ page }) => {
    await page.goto('/dashboard/models');

    const registerBtn = page.locator('button:has-text("Register Model")');
    await registerBtn.click();

    // Form should appear
    await expect(page.locator('label:has-text("Alias")')).toBeVisible();
    await expect(page.locator('label:has-text("Model Name")')).toBeVisible();
  });

  test('should register a new model', async ({ page }) => {
    await page.goto('/dashboard/models');

    // Open form
    const registerBtn = page.locator('button:has-text("Register Model")');
    await registerBtn.click();

    // Fill form
    const aliasInput = page.locator('input[placeholder="gpt-4o"]');
    await aliasInput.fill('test-model');

    // Model name input (with placeholder "openai/gpt-4o")
    const modelNameInput = page.locator('input[placeholder="openai/gpt-4o"]');
    await modelNameInput.fill('openai/gpt-4o-mini');

    // Submit
    const registerModelBtn = page.locator('button:has-text("Register Model")');
    await registerModelBtn.click();

    // Should see the model in the list
    await expect(page.locator('text=test-model')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=openai')).toBeVisible();
  });

  test('should show provider badge', async ({ page }) => {
    await page.goto('/dashboard/models');

    // Open form
    const registerBtn = page.locator('button:has-text("Register Model")');
    await registerBtn.click();

    // Fill form
    const aliasInput = page.locator('input[placeholder="gpt-4o"]');
    await aliasInput.fill('anthropic-test');

    const modelNameInput = page.locator('input[placeholder="openai/gpt-4o"]');
    await modelNameInput.fill('anthropic/claude-3-sonnet');

    const registerModelBtn = page.locator('button:has-text("Register Model")');
    await registerModelBtn.click();

    // Should show anthropic provider badge
    await expect(page.locator('text=anthropic').first()).toBeVisible({ timeout: 5000 });
  });

  test('should delete a model', async ({ page }) => {
    await page.goto('/dashboard/models');

    // Create a model first
    const registerBtn = page.locator('button:has-text("Register Model")');
    await registerBtn.click();

    const aliasInput = page.locator('input[placeholder="gpt-4o"]');
    await aliasInput.fill('delete-me');

    const modelNameInput = page.locator('input[placeholder="openai/gpt-4o"]');
    await modelNameInput.fill('openai/gpt-4o-mini');

    const registerModelBtn = page.locator('button:has-text("Register Model")');
    await registerModelBtn.click();

    await expect(page.locator('text=delete-me')).toBeVisible({ timeout: 5000 });

    // Delete the model
    const deleteBtn = page.locator('button:has-text("Delete"):near(:text("delete-me"))');
    await deleteBtn.click();

    // Confirm deletion
    const confirmBtn = page.locator('button:has-text("Confirm?")');
    await confirmBtn.click();

    // Model should be gone
    await expect(page.locator('text=delete-me')).not.toBeVisible({ timeout: 5000 });
  });
});
