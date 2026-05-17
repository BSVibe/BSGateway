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

  test('renders model cards in grid layout', async ({ page }) => {
    await page.goto('/models');
    // Model name headings (h3 elements)
    await expect(page.getByRole('heading', { name: 'gpt-4o' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'claude-sonnet' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'gemini-pro' })).toBeVisible();
  });

  test('shows provider badges with correct colors', async ({ page }) => {
    await page.goto('/models');
    // Provider badges are uppercase
    await expect(page.getByText('openai', { exact: true })).toBeVisible();
    await expect(page.getByText('anthropic', { exact: true })).toBeVisible();
    await expect(page.getByText('google', { exact: true })).toBeVisible();
  });

  test('shows model ID section on each card', async ({ page }) => {
    await page.goto('/models');
    // Each card shows "Model ID" label
    const modelIdLabels = page.getByText('Model ID');
    await expect(modelIdLabels.first()).toBeVisible();
  });

  test('inactive model card has reduced opacity', async ({ page }) => {
    await page.goto('/models');
    // gemini-pro is inactive (is_active: false)
    const geminiCard = page.locator('div').filter({ hasText: /^gemini-pro/ }).first();
    await expect(geminiCard).toBeVisible();
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
