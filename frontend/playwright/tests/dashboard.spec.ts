import { test, expect } from '@playwright/test';

test.describe('Dashboard Smoke & Metrics Regression', () => {
  test.beforeEach(async ({ page }) => {
    // Listen for uncaught console errors
    page.on('console', msg => {
      if (msg.type() === 'error') {
        // Log for debugging during test runs
        console.error(`Browser console error: ${msg.text()}`);
      }
    });
  });

  test('TEST 1: Dashboard loads successfully with header and selectors', async ({ page }) => {
    const response = await page.goto('/');
    expect(response?.status()).toBe(200);

    // 1. Verify main application header & title
    const header = page.locator('header');
    await expect(header).toBeVisible();
    await expect(page.getByRole('heading', { name: 'ADO Pipeline Insight' })).toBeVisible();
    await expect(page.getByText('Pipeline Performance & AI Duration Optimizer')).toBeVisible();

    // 2. Verify all four filter selectors are present in the controls bar
    const orgSelect = page.getByRole('combobox', { name: /Org/i }).or(page.getByTestId('organization-select'));
    const projectSelect = page.getByRole('combobox', { name: /Project/i }).or(page.getByTestId('project-select'));
    const pipelineSelect = page.getByRole('combobox', { name: /Pipeline/i }).or(page.getByTestId('pipeline-select'));
    const windowSelect = page.getByRole('combobox', { name: /Window/i }).or(page.getByTestId('window-select'));

    await expect(orgSelect).toBeVisible();
    await expect(projectSelect).toBeVisible();
    await expect(pipelineSelect).toBeVisible();
    await expect(windowSelect).toBeVisible();

    // 3. Verify connection status indicates CONNECTED
    const status = page.locator('.status').or(page.getByTestId('connection-status'));
    await expect(status).toBeVisible();
    await expect(status).toContainText('CONNECTED');

    // 4. Verify no fatal UI error box is displayed
    const fatalError = page.locator('.errorBox');
    await expect(fatalError).not.toBeVisible();
  });

  test('TEST 2: Dashboard metrics cards and trend panels display valid rendered values', async ({ page }) => {
    // Set up network synchronization for the summary response before navigation
    const summaryPromise = page.waitForResponse(
      res => res.url().includes('/api/v1/summary') && res.url().includes('days=90') && res.status() === 200,
      { timeout: 35_000 }
    );

    await page.goto('/');
    await summaryPromise;
    const completedRunsCard = page.locator('.metric').filter({ hasText: 'Completed Runs' }).or(page.getByTestId('completed-runs'));
    const successfulRunsCard = page.locator('.metric').filter({ hasText: 'Successful Runs' }).or(page.getByTestId('successful-runs'));
    const failedRunsCard = page.locator('.metric').filter({ hasText: 'Failed Runs' }).or(page.getByTestId('failed-runs'));
    const avgDurationCard = page.locator('.metric').filter({ hasText: 'Build Average Duration' }).or(page.getByTestId('build-average-duration'));
    const queueTimeCard = page.locator('.metric').filter({ hasText: 'Average Queue Time' }).or(page.getByTestId('average-queue-time'));
    const topBottleneckCard = page.locator('.metric').filter({ hasText: 'Top Bottleneck' }).or(page.getByTestId('top-bottleneck'));

    // Verify all metric cards are visible
    await expect(completedRunsCard).toBeVisible();
    await expect(successfulRunsCard).toBeVisible();
    await expect(failedRunsCard).toBeVisible();
    await expect(avgDurationCard).toBeVisible();
    await expect(queueTimeCard).toBeVisible();
    await expect(topBottleneckCard).toBeVisible();

    // Verify cards contain meaningful, rendered values (not placeholders "..." or empty)
    // Matches numeric values (e.g., "32 runs", "31 runs", "0 runs")
    await expect(completedRunsCard.locator('.metricValue')).toHaveText(/\d+\s*(runs)?/, { timeout: 30_000 });
    await expect(successfulRunsCard.locator('.metricValue')).toHaveText(/\d+\s*(runs)?/, { timeout: 30_000 });
    await expect(failedRunsCard.locator('.metricValue')).toHaveText(/\d+\s*(runs)?/, { timeout: 30_000 });

    // Duration values match formatted time (e.g., "11s", "2m 5s", "0s")
    await expect(avgDurationCard.locator('.metricValue')).toHaveText(/\d+(s|m)/, { timeout: 30_000 });
    await expect(queueTimeCard.locator('.metricValue')).toHaveText(/\d+(s|m)/, { timeout: 30_000 });

    // Top bottleneck is non-empty string
    const bottleneckText = await topBottleneckCard.locator('.metricValue').textContent();
    expect(bottleneckText).toBeTruthy();
    expect(bottleneckText?.trim()).not.toBe('...');

    // Verify trend and stage panels exist
    const buildDurationTrend = page.getByRole('heading', { name: 'Build Duration Trend' });
    const stageAverageDuration = page.getByRole('heading', { name: 'Stage Average Duration' });
    await expect(buildDurationTrend).toBeVisible();
    await expect(stageAverageDuration).toBeVisible();
  });
});
