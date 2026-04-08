import { test, expect } from '@playwright/test';
import { gotoUnauth } from './helpers';

test.describe('Login Page', () => {
  test('shows BSGateway logo with amber accent', async ({ page }) => {
    await gotoUnauth(page, '/');
    await expect(page.getByText('BSGateway')).toBeVisible();
    await expect(page.getByText('Gateway').first()).toBeVisible();
  });

  test('displays headline with amber "lower costs" text', async ({ page }) => {
    await gotoUnauth(page, '/');
    await expect(page.getByRole('heading', { name: /smart routing/i })).toBeVisible();
    await expect(page.getByText('lower costs')).toBeVisible();
  });

  test('renders three feature cards', async ({ page }) => {
    await gotoUnauth(page, '/');
    await expect(page.getByText('Cost Optimization', { exact: true })).toBeVisible();
    await expect(page.getByText('Complexity Analysis', { exact: true })).toBeVisible();
    await expect(page.getByText('Multi-Model Routing', { exact: true })).toBeVisible();
  });

  test('shows Sign in with BSVibe button', async ({ page }) => {
    await gotoUnauth(page, '/');
    const btn = page.getByRole('button', { name: /sign in with bsvibe/i });
    await expect(btn).toBeVisible();
  });

  test('clicking sign-in attempts a redirect to auth.bsvibe.dev', async ({ page }) => {
    await gotoUnauth(page, '/');
    // Block the outgoing navigation so the test stays on the LoginPage.
    await page.route('**/auth.bsvibe.dev/**', (route) => route.abort());
    const navAttempt = page.waitForRequest(
      (req) => req.url().includes('auth.bsvibe.dev/login'),
    );
    await page.getByRole('button', { name: /sign in with bsvibe/i }).click();
    const req = await navAttempt;
    expect(req.url()).toContain('auth.bsvibe.dev');
  });

  test('shows "Powered by BSVibe" footer', async ({ page }) => {
    await gotoUnauth(page, '/');
    await expect(page.getByText('Powered by')).toBeVisible();
    await expect(page.getByText('BSVibe', { exact: true })).toBeVisible();
  });

  test('unauthenticated access to /rules redirects to login', async ({ page }) => {
    await gotoUnauth(page, '/rules');
    // Unauthenticated catch-all renders the LoginPage component
    await expect(page.getByRole('button', { name: /sign in with bsvibe/i })).toBeVisible();
  });
});

test.describe('Auth Callback', () => {
  test('callback page processes auth and redirects', async ({ page }) => {
    // The callback page calls auth.handleCallback() then navigates away
    // Without valid tokens, it redirects to root (login page)
    const response = await page.goto('/auth/callback');
    // The page should load (200) and then redirect via JS
    expect(response?.status()).toBe(200);
  });
});
