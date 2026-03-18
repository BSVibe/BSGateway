import { test, expect } from '@playwright/test';

const API_KEY = 'bsg_dev-test-key-do-not-use-in-production-000';

test.describe('Rules Management', () => {
  test.beforeEach(async ({ page }) => {
    // Login before each test
    await page.goto('/');
    const input = page.locator('input[type="text"]');
    await input.fill(API_KEY);
    const button = page.locator('button[type="submit"]');
    await button.click();
    await page.waitForURL('/dashboard', { timeout: 5000 });
  });

  test('should navigate to Rules page', async ({ page }) => {
    await page.goto('/dashboard/rules');
    await expect(page.locator('h2')).toContainText('Routing Rules');
  });

  test('should open create rule form', async ({ page }) => {
    await page.goto('/dashboard/rules');

    const newBtn = page.locator('button:has-text("New Rule")');
    await newBtn.click();

    // Form should appear
    await expect(page.locator('label:has-text("Name")')).toBeVisible();
    await expect(page.locator('label:has-text("Target Model")')).toBeVisible();
  });

  test('should create a new rule', async ({ page }) => {
    await page.goto('/dashboard/rules');

    // Open form
    const newBtn = page.locator('button:has-text("New Rule")');
    await newBtn.click();

    // Fill form
    const nameInput = page.locator('input[placeholder=""]').first();
    await nameInput.fill('Test Rule');

    const priorityInput = page.locator('input[type="number"]');
    await priorityInput.fill('1');

    // Target model input (second text input)
    const inputs = page.locator('input:not([type="number"])');
    const targetModelInput = await inputs.nth(1);
    await targetModelInput.fill('gpt-4o');

    // Submit
    const createBtn = page.locator('button:has-text("Create Rule")');
    await createBtn.click();

    // Should see the rule in the list
    await expect(page.locator('text=Test Rule')).toBeVisible({ timeout: 5000 });
  });

  test('should delete a rule', async ({ page }) => {
    await page.goto('/dashboard/rules');

    // Create a rule first
    const newBtn = page.locator('button:has-text("New Rule")');
    await newBtn.click();

    const inputs = page.locator('input:not([type="number"])');
    await inputs.nth(0).fill('Delete Me');

    const priorityInput = page.locator('input[type="number"]');
    await priorityInput.fill('99');

    await inputs.nth(1).fill('gpt-4o');

    const createBtn = page.locator('button:has-text("Create Rule")');
    await createBtn.click();

    await expect(page.locator('text=Delete Me')).toBeVisible({ timeout: 5000 });

    // Delete the rule
    const deleteBtn = page.locator('button:has-text("Delete"):near(:text("Delete Me"))');
    await deleteBtn.click();

    // Confirm deletion
    const confirmBtn = page.locator('button:has-text("Confirm?")');
    await confirmBtn.click();

    // Rule should be gone
    await expect(page.locator('text=Delete Me')).not.toBeVisible({ timeout: 5000 });
  });
});
