import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: [['html'], ['list']],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    // Phase B Batch 2: mobile viewport coverage. Pixel 5 (Mobile Chrome) +
    // iPhone 13 (Mobile Chromium engine — Playwright bundled WebKit hangs
    // page-launch on macOS 26 with DEPENDENCIES_VALIDATED stuck; the
    // viewport / userAgent / isMobile flag still match iPhone 13).
    // See Shared Library Roadmap §B3.
    {
      name: 'pixel-5',
      use: { ...devices['Pixel 5'] },
    },
    {
      name: 'iphone-13',
      use: {
        browserName: 'chromium',
        ...devices['iPhone 13'],
        defaultBrowserType: 'chromium',
      },
    },
  ],
  webServer: {
    // Was `vite --port 5173`; now `next dev -p 5173`. Test surface is unchanged.
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
