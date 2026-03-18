import { test, expect } from '@playwright/test';

const API_KEY = 'bsg_dev-test-key-do-not-use-in-production-000';
const API_URL = 'http://localhost:8000/api/v1';
const APP_URL = 'http://localhost:5173';

test.describe('Authentication Flow', () => {
  test('login with API key and access dashboard', async ({ page }) => {
    // 1️⃣ Navigate to login
    await page.goto(APP_URL);
    await expect(page).toHaveTitle(/BSGateway/);

    // 2️⃣ Fill in API key
    await page.fill('input[placeholder="bsg_..."]', API_KEY);

    // 3️⃣ Click login
    await page.click('button:has-text("Sign in")');

    // 4️⃣ Should redirect to dashboard
    await page.waitForURL('**/');
    await expect(page.locator('text=Dashboard')).toBeVisible();

    // 5️⃣ Verify tenant name is displayed
    await expect(page.locator('text=Dev Team')).toBeVisible();

    // 6️⃣ Token should be stored in localStorage
    const token = await page.evaluate(() => localStorage.getItem('bsg_token'));
    expect(token).toBeTruthy();
    expect(token).toMatch(/^eyJ/); // JWT format check
  });

  test('API key exchange returns correct tenant info', async () => {
    const response = await fetch(`${API_URL}/auth/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: API_KEY }),
    });

    expect(response.status).toBe(200);
    const data = await response.json();

    expect(data.token).toBeTruthy();
    expect(data.tenant_id).toBeTruthy();
    expect(data.tenant_slug).toBe('dev-team');
    expect(data.tenant_name).toBe('Dev Team');
    expect(data.scopes).toContain('chat');
    expect(data.scopes).toContain('admin');
  });

  test('invalid API key returns 401', async () => {
    const response = await fetch(`${API_URL}/auth/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: 'bsg_invalid' }),
    });

    expect(response.status).toBe(401);
    const data = await response.json();
    expect(data.detail).toMatch(/Invalid or expired/);
  });

  test('logout clears token and redirects to login', async ({ page }) => {
    // Login first
    await page.goto(APP_URL);
    await page.fill('input[placeholder="bsg_..."]', API_KEY);
    await page.click('button:has-text("Sign in")');
    await page.waitForURL('**/');

    // Verify logged in
    const token = await page.evaluate(() => localStorage.getItem('bsg_token'));
    expect(token).toBeTruthy();

    // Click logout
    await page.click('button:has-text("Logout")');

    // Should redirect to login
    await page.waitForURL('**/dashboard');
    await expect(page.locator('text=API Key')).toBeVisible();

    // Token should be cleared
    const clearedToken = await page.evaluate(() => localStorage.getItem('bsg_token'));
    expect(clearedToken).toBeNull();
  });
});

test.describe('Dashboard Navigation', () => {
  test.beforeEach(async ({ page }) => {
    // Login before each test
    await page.goto(APP_URL);
    await page.fill('input[placeholder="bsg_..."]', API_KEY);
    await page.click('button:has-text("Sign in")');
    await page.waitForURL('**/');
  });

  test('can navigate between pages', async ({ page }) => {
    // Verify Dashboard
    await expect(page.locator('text=Dashboard')).toBeVisible();

    // Navigate to Rules
    await page.click('text=Rules');
    await expect(page.locator('text=Rules')).toBeVisible();

    // Navigate to Models
    await page.click('text=Models');
    await expect(page.locator('text=Models')).toBeVisible();

    // Navigate to Usage
    await page.click('text=Usage');
    await expect(page.locator('text=Usage')).toBeVisible();

    // Navigate to Audit
    await page.click('text=Audit Log');
    await expect(page.locator('text=Audit Log')).toBeVisible();
  });

  test('sidebar displays tenant name', async ({ page }) => {
    await expect(page.locator('text=Dev Team')).toBeVisible();
    await expect(page.locator('text=BSGateway')).toBeVisible();
  });
});

test.describe('API Integration', () => {
  let token: string;

  test.beforeEach(async () => {
    // Get token via API
    const response = await fetch(`${API_URL}/auth/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: API_KEY }),
    });
    const data = await response.json();
    token = data.token;
  });

  test('can fetch rules with JWT', async () => {
    const response = await fetch(
      `${API_URL}/tenants/144154d8-d030-43ba-a75b-f37674524f80/rules`,
      {
        headers: { Authorization: `Bearer ${token}` },
      }
    );

    expect(response.status).toBe(200);
    const data = await response.json();
    expect(Array.isArray(data)).toBe(true);
  });

  test('can fetch models with JWT', async () => {
    const response = await fetch(
      `${API_URL}/tenants/144154d8-d030-43ba-a75b-f37674524f80/models`,
      {
        headers: { Authorization: `Bearer ${token}` },
      }
    );

    expect(response.status).toBe(200);
    const data = await response.json();
    expect(Array.isArray(data)).toBe(true);
  });

  test('invalid token returns 401', async () => {
    const response = await fetch(
      `${API_URL}/tenants/144154d8-d030-43ba-a75b-f37674524f80/rules`,
      {
        headers: { Authorization: 'Bearer invalid.token.here' },
      }
    );

    expect(response.status).toBe(401);
  });
});
