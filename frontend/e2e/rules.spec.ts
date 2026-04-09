import { test, expect } from '@playwright/test';
import {
  injectAuth,
  mockTenantInfo,
  mockGet,
  MOCK_RULES,
  MOCK_INTENTS,
  MOCK_EXAMPLES,
  MOCK_MODELS,
} from './helpers';

test.describe('Routes Page (Notion Mail-style)', () => {
  test.beforeEach(async ({ page }) => {
    await injectAuth(page);
    await mockTenantInfo(page);
    await mockGet(page, '/rules', MOCK_RULES);
    await mockGet(page, '/intents', MOCK_INTENTS);
    await mockGet(page, '/intents/intent-1/examples', MOCK_EXAMPLES);
    await mockGet(page, '/models', MOCK_MODELS);
    // EmbeddingSettingsCard fetches this on mount; default to "not configured".
    await mockGet(page, '/embedding-settings', null);
  });

  test('displays page heading and natural-language subtitle', async ({ page }) => {
    await page.goto('/rules');
    await expect(page.getByRole('heading', { name: /routing rules/i })).toBeVisible();
    await expect(
      page.getByText(/describe what kind of requests should go to which model/i),
    ).toBeVisible();
  });

  test('renders a route card for each intent + rule pair', async ({ page }) => {
    await page.goto('/rules');
    await expect(page.getByText('Code review and debugging requests')).toBeVisible();
  });

  test('renders a default fallback card at the bottom', async ({ page }) => {
    await page.goto('/rules');
    await expect(page.getByText('Default fallback')).toBeVisible();
    await expect(page.getByText('Used when no other rule matches.')).toBeVisible();
  });

  test('shows priority badge on non-default cards', async ({ page }) => {
    await page.goto('/rules');
    await expect(page.getByText('P0')).toBeVisible();
  });

  test('shows examples count on cards with intent', async ({ page }) => {
    await page.goto('/rules');
    await expect(page.getByText('2 examples')).toBeVisible();
  });

  test('Add Rule button opens the create modal', async ({ page }) => {
    await page.goto('/rules');
    await page.getByRole('button', { name: /add rule/i }).first().click();
    await expect(page.getByRole('heading', { name: /add routing rule/i })).toBeVisible();
  });

  test('create modal has natural-language description textarea', async ({ page }) => {
    await page.goto('/rules');
    await page.getByRole('button', { name: /add rule/i }).first().click();
    await expect(page.getByText(/어떤 요청을 라우팅할까요/)).toBeVisible();
    await expect(page.getByPlaceholder(/코드 리뷰나 디버깅/)).toBeVisible();
  });

  test('create modal has model selector dropdown populated from models', async ({ page }) => {
    await page.goto('/rules');
    await page.getByRole('button', { name: /add rule/i }).first().click();
    await expect(page.getByText(/어떤 모델로 보낼까요/)).toBeVisible();
    const select = page.locator('select').first();
    await expect(select).toBeVisible();
    // Should contain registered model options
    await expect(select.locator('option', { hasText: /gpt-4o/ })).toHaveCount(1);
  });

  test('create modal Create button disabled until description and model are filled', async ({ page }) => {
    await page.goto('/rules');
    await page.getByRole('button', { name: /add rule/i }).first().click();
    const createBtn = page.getByRole('button', { name: /^create$/i });
    await expect(createBtn).toBeDisabled();

    await page.getByPlaceholder(/코드 리뷰나 디버깅/).fill('Translation requests');
    // First model auto-selected from MOCK_MODELS, so button should now be enabled
    await expect(createBtn).toBeEnabled();
  });

  test('create modal has collapsible examples section', async ({ page }) => {
    await page.goto('/rules');
    await page.getByRole('button', { name: /add rule/i }).first().click();
    await expect(page.getByText(/예시 문장 추가/)).toBeVisible();
    // Examples input should not be visible until expanded
    await expect(page.getByPlaceholder(/이 코드 리뷰해줘/)).not.toBeVisible();
    await page.getByText(/예시 문장 추가/).click();
    await expect(page.getByPlaceholder(/이 코드 리뷰해줘/)).toBeVisible();
  });

  test('create modal Cancel button closes the modal', async ({ page }) => {
    await page.goto('/rules');
    await page.getByRole('button', { name: /add rule/i }).first().click();
    await expect(page.getByRole('heading', { name: /add routing rule/i })).toBeVisible();
    await page.getByRole('button', { name: /^cancel$/i }).click();
    await expect(page.getByRole('heading', { name: /add routing rule/i })).not.toBeVisible();
  });

  test('expanding card reveals example phrases', async ({ page }) => {
    await page.goto('/rules');
    await page.getByText('2 examples').click();
    await expect(page.getByText('Example phrases')).toBeVisible();
    await expect(page.getByText('Please review this code')).toBeVisible();
    await expect(page.getByText('Help me debug this error')).toBeVisible();
  });

  test('empty state shows when no rules and no intents exist', async ({ page }) => {
    await mockGet(page, '/rules', []);
    await mockGet(page, '/intents', []);
    await page.goto('/rules');
    await expect(page.getByText('No routing rules yet')).toBeVisible();
    await expect(page.getByText(/create your first routing rule/i)).toBeVisible();
  });

  test('/intents path redirects to /rules', async ({ page }) => {
    await page.goto('/intents');
    await expect(page).toHaveURL(/\/rules$/);
    await expect(page.getByRole('heading', { name: /routing rules/i })).toBeVisible();
  });

  test('embedding settings card shows "disabled" badge when not configured', async ({ page }) => {
    await page.goto('/rules');
    const card = page.getByRole('button', { name: /Embedding model/ });
    await expect(card).toBeVisible();
    await expect(card.getByText('disabled', { exact: true })).toBeVisible();
    await expect(
      page.getByText(/no embedding model configured/i),
    ).toBeVisible();
  });

  test('embedding settings card expands and shows preset buttons', async ({ page }) => {
    await page.goto('/rules');
    await page.getByRole('button', { name: /Embedding model/ }).click();
    await expect(page.getByPlaceholder('text-embedding-3-small')).toBeVisible();
    await expect(page.getByRole('button', { name: 'OpenAI text-embedding-3-small' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Ollama nomic-embed-text' })).toBeVisible();
  });

  test('default fallback card shows missing badge when no default rule exists', async ({ page }) => {
    // Override MOCK_RULES with a list that has NO default rule
    const rulesWithoutDefault = MOCK_RULES.filter((r) => !r.is_default);
    await mockGet(page, '/rules', rulesWithoutDefault);
    await page.goto('/rules');
    await expect(page.getByText('Default fallback')).toBeVisible();
    await expect(page.getByText('missing', { exact: true })).toBeVisible();
    await expect(
      page.getByText(/unmatched requests return 400/i),
    ).toBeVisible();
  });

  test('default fallback card shows active when default rule configured', async ({ page }) => {
    // MOCK_RULES already includes an is_default rule
    await page.goto('/rules');
    await expect(
      page.getByText('Used when no other rule matches.'),
    ).toBeVisible();
  });

  test('embedding settings card shows active state when configured', async ({ page }) => {
    await mockGet(page, '/embedding-settings', {
      model: 'text-embedding-3-small',
      api_base: null,
      timeout: 10,
      max_input_length: 8000,
    });
    await page.goto('/rules');
    const card = page.getByRole('button', { name: /Embedding model/ });
    await expect(card.getByText('active', { exact: true })).toBeVisible();
    await expect(
      page.getByText(/text-embedding-3-small.*classify intents/i),
    ).toBeVisible();
  });
});
