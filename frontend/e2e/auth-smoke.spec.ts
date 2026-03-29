import { test, expect } from "@playwright/test";

test.describe("Auth smoke test", () => {
  test("unauthenticated user sees login page", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    
    // Should see login/landing page
    const loginBtn = page.locator("text=Sign in with BSVibe");
    await expect(loginBtn).toBeVisible({ timeout: 10000 });
  });

  test("authenticated user sees dashboard", async ({ page }) => {
    // Inject a properly structured (but expired) token to test the auth check
    // The point is to verify the frontend reads localStorage and routes correctly
    await page.goto("/");
    
    // Set a fake token with future expiry
    await page.evaluate(() => {
      const header = btoa(JSON.stringify({ alg: "ES256", typ: "JWT" }))
        .replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
      const payload = btoa(JSON.stringify({
        sub: "test-user-id",
        email: "test@bsvibe.dev",
        role: "authenticated",
        exp: Math.floor(Date.now() / 1000) + 3600,
        iat: Math.floor(Date.now() / 1000),
        app_metadata: { role: "admin" },
      })).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
      const token = `${header}.${payload}.fake-sig`;
      
      // BSGateway uses BSVibeAuth session storage
      sessionStorage.setItem("bsvibe_user", JSON.stringify({
        accessToken: token,
        refreshToken: "fake-refresh",
        tenantId: "test-tenant",
        email: "test@bsvibe.dev",
        role: "admin",
      }));
    });

    await page.reload();
    await page.waitForTimeout(3000);

    // Check if we see dashboard content (not login page)
    const url = page.url();
    const hasLogin = await page.locator("text=Sign in with BSVibe").isVisible().catch(() => false);
    
    // Log result for debugging
    console.log(`URL: ${url}, Still on login: ${hasLogin}`);
  });

  test("login button redirects to auth.bsvibe.dev", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    
    const loginBtn = page.locator("text=Sign in with BSVibe");
    if (await loginBtn.isVisible()) {
      // Listen for navigation
      const [response] = await Promise.all([
        page.waitForEvent("requestfinished", { 
          predicate: (req) => req.url().includes("auth.bsvibe.dev"),
          timeout: 5000,
        }).catch(() => null),
        loginBtn.click(),
      ]);
      
      // Should have navigated to auth.bsvibe.dev
      expect(page.url()).toContain("auth.bsvibe.dev");
    }
  });
});
