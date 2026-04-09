import { test, expect } from '@playwright/test';
import { injectAuth, mockTenantInfo, mockGet, mockPost, MOCK_MODELS, MOCK_RULES, MOCK_TEST_RESULT } from './helpers';

test.describe('Routing Simulator Page', () => {
  test.beforeEach(async ({ page }) => {
    await injectAuth(page);
    await mockTenantInfo(page);
    await mockGet(page, '/models', MOCK_MODELS);
    await mockGet(page, '/rules', MOCK_RULES);
  });

  test('displays page heading', async ({ page }) => {
    await page.goto('/test');
    await expect(page.getByRole('heading', { name: /routing simulator/i })).toBeVisible();
    await expect(page.getByText('Test routing logic before deployment')).toBeVisible();
  });

  test('shows split panel layout with Test Input and empty result', async ({ page }) => {
    await page.goto('/test');
    await expect(page.getByText('Test Input')).toBeVisible();
    await expect(page.getByText('No test run yet')).toBeVisible();
  });

  test('prompt textarea is visible with placeholder', async ({ page }) => {
    await page.goto('/test');
    await expect(page.getByPlaceholder(/paste your llm prompt here/i)).toBeVisible();
  });

  test('Run Simulation button disabled without prompt', async ({ page }) => {
    await page.goto('/test');
    const btn = page.getByRole('button', { name: /run simulation/i });
    await expect(btn).toBeDisabled();
  });

  test('Add Message button adds another message input', async ({ page }) => {
    await page.goto('/test');
    await page.getByText('Add Message').click();
    const textareas = page.locator('textarea');
    await expect(textareas).toHaveCount(2);
  });

  test('shows simulation result after test run', async ({ page }) => {
    await mockPost(page, '/rules/test', MOCK_TEST_RESULT);
    await page.goto('/test');
    await page.getByPlaceholder(/paste your llm prompt here/i).fill('Explain quantum computing');
    await page.getByRole('button', { name: /run simulation/i }).click();

    await expect(page.getByText('Simulation Result')).toBeVisible();
    await expect(page.getByText('openai/gpt-4o').first()).toBeVisible();
    await expect(page.getByText('MATCHED', { exact: true })).toBeVisible();
  });

  test('result shows matched rule name (description, not slug)', async ({ page }) => {
    await mockPost(page, '/rules/test', MOCK_TEST_RESULT);
    await page.goto('/test');
    await page.getByPlaceholder(/paste your llm prompt here/i).fill('Test prompt');
    await page.getByRole('button', { name: /run simulation/i }).click();

    await expect(page.getByText(/Matched rule:.*High Priority Router/i)).toBeVisible();
  });

  test('result shows routing path visualization', async ({ page }) => {
    await mockPost(page, '/rules/test', MOCK_TEST_RESULT);
    await page.goto('/test');
    await page.getByPlaceholder(/paste your llm prompt here/i).fill('Test prompt');
    await page.getByRole('button', { name: /run simulation/i }).click();

    const main = page.getByRole('main');
    await expect(main.getByText('Input', { exact: true })).toBeVisible();
    await expect(main.getByText('Classifier')).toBeVisible();
    await expect(main.getByText('Routing Path')).toBeVisible();
  });

  test('shows NO MATCH badge when no rule matches', async ({ page }) => {
    const noMatchResult = {
      matched_rule: null,
      target_model: null,
      evaluation_trace: [],
      context: { estimated_tokens: 5, conversation_turns: 1 },
    };
    await mockPost(page, '/rules/test', noMatchResult);
    await page.goto('/test');
    await page.getByPlaceholder(/paste your llm prompt here/i).fill('Test prompt');
    await page.getByRole('button', { name: /run simulation/i }).click();

    await expect(page.getByText('NO MATCH', { exact: true })).toBeVisible();
  });
});
