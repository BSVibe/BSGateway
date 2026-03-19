import { test, expect } from '@playwright/test';
import { setupAuth, setupApiMocks } from './fixtures/mock-api';

test.describe('Models Management', () => {
  test.beforeEach(async ({ page }) => {
    await setupAuth(page);
    await setupApiMocks(page);
    await page.goto('/dashboard/models');
    await expect(page.locator('h2')).toContainText('Models', { timeout: 5000 });
  });

  test('displays existing models', async ({ page }) => {
    // Use structural locator to distinguish model names from litellm names
    await expect(page.locator('.font-medium:has-text("claude-sonnet")')).toBeVisible();
    await expect(page.locator('.font-medium:has-text("gpt-4o")').first()).toBeVisible();
    await expect(page.locator('.font-medium:has-text("gpt-4o-mini")')).toBeVisible();
  });

  test('shows provider badges', async ({ page }) => {
    await expect(page.locator('.bg-blue-100:has-text("anthropic"), .bg-purple-100:has-text("anthropic"), span:has-text("anthropic")').first()).toBeVisible();
    await expect(page.locator('span:has-text("openai")').first()).toBeVisible();
  });

  test('shows inactive badge for disabled models', async ({ page }) => {
    await expect(page.getByText('inactive', { exact: true })).toBeVisible();
  });

  test('shows litellm model names', async ({ page }) => {
    await expect(page.locator('text=anthropic/claude-sonnet-4-20250514')).toBeVisible();
    await expect(page.locator('.font-mono:has-text("openai/gpt-4o")').first()).toBeVisible();
  });

  test('opens and closes register model form', async ({ page }) => {
    await expect(page.locator('label:has-text("Alias")')).not.toBeVisible();

    await page.click('button:has-text("Register Model")');
    await expect(page.locator('label:has-text("Alias")')).toBeVisible();
    await expect(page.locator('label:has-text("Model Name")')).toBeVisible();

    await page.click('button:has-text("Cancel")');
    await expect(page.locator('label:has-text("Alias")')).not.toBeVisible();
  });

  test('registers a new model', async ({ page }) => {
    await page.click('button:has-text("Register Model")');

    await page.fill('input[placeholder="gpt-4o"]', 'test-model-e2e');
    await page.fill('input[placeholder="openai/gpt-4o"]', 'openai/gpt-4o-test');

    await page.click('button:has-text("Register Model")');

    await expect(page.locator('text=test-model-e2e')).toBeVisible({ timeout: 5000 });
  });

  test('registers model with optional API base', async ({ page }) => {
    await page.click('button:has-text("Register Model")');

    await page.fill('input[placeholder="gpt-4o"]', 'ollama-model');
    await page.fill('input[placeholder="openai/gpt-4o"]', 'ollama/llama3');
    await page.fill('input[placeholder="http://localhost:11434"]', 'http://myserver:11434');

    await page.click('button:has-text("Register Model")');
    await expect(page.locator('text=ollama-model')).toBeVisible({ timeout: 5000 });
  });

  test('deletes a model with confirmation', async ({ page }) => {
    // Use structural locator - first model row's button
    const firstModelRow = page.locator('.divide-y > div').first();
    const actionBtn = firstModelRow.locator('button');

    // First click: Delete → Confirm?
    await actionBtn.click();
    await expect(actionBtn).toContainText('Confirm?');

    // Second click: confirm deletion
    await actionBtn.click();

    // claude-sonnet should be gone
    await expect(page.locator('.font-medium:has-text("claude-sonnet")')).not.toBeVisible({ timeout: 5000 });
  });
});
