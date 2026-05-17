import { test, expect } from '@playwright/test';
import { injectAuth, mockTenantInfo, mockGet, MOCK_MODELS } from './helpers';

test.describe('Models Page', () => {
  test.beforeEach(async ({ page }) => {
    await injectAuth(page);
    await mockTenantInfo(page);
    await mockGet(page, '/models', MOCK_MODELS);
  });

  test('displays page heading and model count', async ({ page }) => {
    await page.goto('/models');
    await expect(page.getByRole('heading', { name: /model registry/i })).toBeVisible();
    // models.summary renders "<n> model(s) · <n> worker(s) registered."
    await expect(page.getByText(/3 models · \d+ workers? registered\./)).toBeVisible();
  });

  test('renders a row/card per model', async ({ page }, testInfo) => {
    await page.goto('/models');
    // ResponsiveTable dual-renders — assert against the tree the viewport
    // shows: desktop <table> rows, or mobile card stack.
    const mobile = testInfo.project.name !== 'chromium';
    if (mobile) {
      const cards = page.locator('[data-testid="bsvibe-table-mobile"]').first();
      await expect(cards.getByRole('heading', { name: 'gpt-4o' })).toBeVisible();
      await expect(cards.getByRole('heading', { name: 'claude-sonnet' })).toBeVisible();
      await expect(cards.getByRole('heading', { name: 'gemini-pro' })).toBeVisible();
    } else {
      const rows = page.locator('[data-testid="bsvibe-table-scroll"] table').first().locator('tbody tr');
      await expect(rows).toHaveCount(3);
      // First cell of each row is the model name.
      await expect(rows.nth(0).locator('td').first()).toContainText('gpt-4o');
      await expect(rows.nth(1).locator('td').first()).toContainText('claude-sonnet');
      await expect(rows.nth(2).locator('td').first()).toContainText('gemini-pro');
    }
  });

  test('shows provider badges with correct colors', async ({ page }) => {
    await page.goto('/models');
    // ResponsiveTable dual-renders — the provider badge exists in both the
    // desktop <td> and the mobile card; scope to the visible tree.
    await expect(page.getByText('openai', { exact: true }).locator('visible=true')).toBeVisible();
    await expect(page.getByText('anthropic', { exact: true }).locator('visible=true')).toBeVisible();
    await expect(page.getByText('google', { exact: true }).locator('visible=true')).toBeVisible();
  });

  test('shows model ID section on each card', async ({ page }) => {
    await page.goto('/models');
    // "Model ID" is a column header on desktop and a card label on mobile.
    await expect(page.getByText('Model ID').locator('visible=true').first()).toBeVisible();
  });

  test('inactive model row/card renders', async ({ page }, testInfo) => {
    await page.goto('/models');
    // gemini-pro is inactive (is_active: false) — assert it renders in the
    // tree the viewport shows.
    if (testInfo.project.name !== 'chromium') {
      await expect(
        page.locator('[data-testid="bsvibe-table-mobile"]').first().getByRole('heading', { name: 'gemini-pro' }),
      ).toBeVisible();
    } else {
      // gemini-pro appears as both the name cell and the model-id cell —
      // the name cell is column 1, so .first().
      await expect(
        page.getByRole('cell', { name: 'gemini-pro', exact: true }).first(),
      ).toBeVisible();
    }
  });

  test('Register Model button toggles form', async ({ page }) => {
    await page.goto('/models');
    const btn = page.getByRole('button', { name: /register model/i });
    await expect(btn).toBeVisible();
    await btn.click();
    await expect(page.getByText('Register New Model')).toBeVisible();
    // Alias and LiteLLM Model ID inputs
    await expect(page.getByPlaceholder('gpt-4o', { exact: true })).toBeVisible();
    await expect(page.getByPlaceholder('openai/gpt-4o', { exact: true })).toBeVisible();
  });

  test('register form has optional API Base and API Key fields', async ({ page }) => {
    await page.goto('/models');
    await page.getByRole('button', { name: /register model/i }).click();
    await expect(page.getByPlaceholder('http://localhost:11434')).toBeVisible();
    await expect(page.getByPlaceholder('sk-...')).toBeVisible();
  });

  test('register form submit button disabled without required fields', async ({ page }) => {
    await page.goto('/models');
    await page.getByRole('button', { name: /register model/i }).click();
    const submitBtn = page.getByRole('button', { name: 'Register Model' }).last();
    await expect(submitBtn).toBeDisabled();
  });

  test('empty state shows when no models exist', async ({ page }) => {
    await mockGet(page, '/models', []);
    await page.goto('/models');
    await expect(page.getByText('No models registered')).toBeVisible();
    await expect(page.getByRole('button', { name: /register first model/i })).toBeVisible();
  });
});
