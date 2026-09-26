import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright E2E configuration for ADO Pipeline Insight.
 * Targets the deployed Azure App Service by default, or an environment-supplied PLAYWRIGHT_BASE_URL.
 */
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'https://app-ado-pipeline-insight-test.azurewebsites.net';

export default defineConfig({
  testDir: './playwright/tests',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  timeout: 60_000,
  expect: {
    timeout: 15_000,
  },
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: 'playwright-report' }],
  ],
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    headless: true,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
