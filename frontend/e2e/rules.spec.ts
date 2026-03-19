import { test, expect } from '@playwright/test';
import { setupAuth, setupApiMocks } from './fixtures/mock-api';

test.describe('Rules Management', () => {
  test.beforeEach(async ({ page }) => {
    await setupAuth(page);
    await setupApiMocks(page);
    await page.goto('/dashboard/rules');
    await expect(page.locator('h2')).toContainText('Routing Rules', { timeout: 5000 });
  });

  test('displays existing rules sorted by priority', async ({ page }) => {
    await expect(page.locator('text=High-priority rule')).toBeVisible();
    await expect(page.locator('text=Default fallback')).toBeVisible();

    // Priority badges - use exact text match to avoid P1 matching P100
    await expect(page.getByText('P1', { exact: true })).toBeVisible();
    await expect(page.getByText('P100', { exact: true })).toBeVisible();
  });

  test('shows default badge on default rules', async ({ page }) => {
    // Use exact match to distinguish "default" badge from "Default fallback" name
    await expect(page.getByText('default', { exact: true })).toBeVisible();
  });

  test('shows condition count for rules with conditions', async ({ page }) => {
    // Code only shows condition count when > 0
    await expect(page.locator('text=1 condition(s)')).toBeVisible();
  });

  test('shows target model for each rule', async ({ page }) => {
    await expect(page.locator('text=Target:')).toHaveCount(2);
    await expect(page.locator('span.font-mono:has-text("claude-sonnet")')).toBeVisible();
    await expect(page.locator('span.font-mono:has-text("gpt-4o-mini")')).toBeVisible();
  });

  test('opens and closes create rule form', async ({ page }) => {
    await expect(page.locator('label:has-text("Name")')).not.toBeVisible();

    await page.click('button:has-text("New Rule")');
    await expect(page.locator('label:has-text("Name")')).toBeVisible();
    await expect(page.locator('label:has-text("Target Model")')).toBeVisible();
    await expect(page.locator('label:has-text("Priority")')).toBeVisible();

    await page.click('button:has-text("Cancel")');
    await expect(page.locator('label:has-text("Name")')).not.toBeVisible();
  });

  test('creates a new rule', async ({ page }) => {
    await page.click('button:has-text("New Rule")');

    // Fill the form - use labels to find adjacent inputs
    await page.locator('label:has-text("Name") + input').fill('Test Rule E2E');
    await page.locator('input[type="number"]').fill('50');
    await page.locator('label:has-text("Target Model") + input').fill('gpt-4o');

    await page.click('button:has-text("Create Rule")');

    await expect(page.locator('text=Test Rule E2E')).toBeVisible({ timeout: 5000 });
  });

  test('deletes a rule with confirmation', async ({ page }) => {
    // Use structural locator for robustness against onBlur
    const firstRuleRow = page.locator('.divide-y > div').first();
    const actionBtn = firstRuleRow.locator('button');

    // First click: shows "Confirm?"
    await actionBtn.click();
    await expect(actionBtn).toContainText('Confirm?');

    // Second click: confirms deletion
    await actionBtn.click();

    await expect(page.locator('text=High-priority rule')).not.toBeVisible({ timeout: 5000 });
  });
});
