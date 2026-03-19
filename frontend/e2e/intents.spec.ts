import { test, expect } from '@playwright/test';
import { setupAuth, setupApiMocks } from './fixtures/mock-api';

test.describe('Intents Management', () => {
  test.beforeEach(async ({ page }) => {
    await setupAuth(page);
    await setupApiMocks(page);
    await page.goto('/dashboard/intents');
    await expect(page.locator('h2')).toContainText('Custom Intents', { timeout: 5000 });
  });

  test('displays existing intents', async ({ page }) => {
    await expect(page.locator('text=summarization')).toBeVisible();
    await expect(page.locator('text=code-generation')).toBeVisible();
  });

  test('shows intent descriptions', async ({ page }) => {
    await expect(page.locator('text=Requests asking to summarize content')).toBeVisible();
    await expect(page.locator('text=Requests to generate code')).toBeVisible();
  });

  test('shows example counts', async ({ page }) => {
    await expect(page.locator('text=2 example(s)')).toBeVisible(); // summarization has 2
    await expect(page.locator('text=1 example(s)')).toBeVisible(); // code-generation has 1
  });

  test('shows inactive badge for disabled intents', async ({ page }) => {
    // code-generation is_active=false
    await expect(page.locator('text=inactive')).toBeVisible();
  });

  test('opens and closes create intent form', async ({ page }) => {
    await expect(page.locator('label:has-text("Name")')).not.toBeVisible();

    await page.click('button:has-text("New Intent")');
    await expect(page.locator('label:has-text("Name")')).toBeVisible();
    await expect(page.locator('label:has-text("Description")')).toBeVisible();
    await expect(page.locator('label:has-text("Examples")')).toBeVisible();
    await expect(page.locator('text=Target Model (optional)')).toBeVisible();

    await page.click('button:has-text("Cancel")');
    await expect(page.locator('label:has-text("Name")')).not.toBeVisible();
  });

  test('creates a new intent with examples', async ({ page }) => {
    await page.click('button:has-text("New Intent")');

    // Fill name
    await page.fill('input[placeholder="summarization"]', 'translation');

    // Fill description
    await page.fill('textarea[placeholder="Requests asking to summarize content"]', 'Translation requests');

    // Fill first example
    const exampleInputs = page.locator('input[placeholder*="Please summarize"]');
    await exampleInputs.first().fill('Translate this to Korean');

    // Add second example
    await page.click('text=+ Add Example');
    const allExampleInputs = page.locator('input[placeholder*="Please summarize"]');
    await allExampleInputs.nth(1).fill('Convert to Spanish');

    // Fill target model
    await page.fill('input[placeholder="gpt-4o"]', 'gpt-4o');

    // Submit
    await page.click('button:has-text("Create Intent")');

    // New intent should appear
    await expect(page.locator('text=translation')).toBeVisible({ timeout: 5000 });
  });

  test('can remove an example from the form', async ({ page }) => {
    await page.click('button:has-text("New Intent")');

    // Add a second example
    await page.click('text=+ Add Example');

    // Should have 2 example inputs and remove buttons
    const removeButtons = page.locator('button:has-text("✕")');
    expect(await removeButtons.count()).toBe(2);

    // Remove one example
    await removeButtons.first().click();

    // Only 1 example left, no remove button (can't remove last)
    expect(await removeButtons.count()).toBe(0);
  });

  test('create button disabled without name or examples', async ({ page }) => {
    await page.click('button:has-text("New Intent")');

    const createBtn = page.locator('button:has-text("Create Intent")');

    // Empty form - button should be disabled
    await expect(createBtn).toBeDisabled();

    // Add name but no example
    await page.fill('input[placeholder="summarization"]', 'test-intent');
    await expect(createBtn).toBeDisabled();

    // Add example too
    await page.fill('input[placeholder*="Please summarize"]', 'Some example');
    await expect(createBtn).toBeEnabled();
  });

  test('deletes an intent with confirmation', async ({ page }) => {
    const deleteBtn = page.locator('button:has-text("Delete")').first();
    await deleteBtn.click();

    await expect(page.locator('button:has-text("Confirm?")')).toBeVisible();
    await page.click('button:has-text("Confirm?")');

    // First intent (summarization) should be gone
    await expect(page.locator('text=summarization')).not.toBeVisible({ timeout: 5000 });
  });
});
