import { test, expect } from '@playwright/test';

test.describe('Persistence & Page Refresh Regression', () => {
  test('TEST 8: Page refresh re-establishes clean connection and retains dashboard data availability', async ({ page }) => {
    // 1. Set up network synchronization for the initial summary request before navigation
    const initialSummaryPromise = page.waitForResponse(
      res => res.url().includes('/api/v1/summary') && res.url().includes('days=90') && res.status() === 200,
      { timeout: 35_000 }
    );

    const initialOptionsPromise = page.waitForResponse(
      res => res.url().includes('/api/v1/options') && res.status() === 200,
      { timeout: 35_000 }
    );

    const response = await page.goto('/');
    expect(response?.status()).toBe(200);

    // 2. Wait for initial summary and options APIs to complete successfully
    await initialSummaryPromise;
    await initialOptionsPromise;

    // 3. Verify connection status and that Completed Runs contains a numeric value
    const status = page.locator('.status').or(page.getByTestId('connection-status'));
    await expect(status).toBeVisible();
    await expect(status).toContainText('CONNECTED');

    const completedRuns = page.locator('.metric').filter({ hasText: 'Completed Runs' }).or(page.getByTestId('completed-runs'));
    await expect(completedRuns.locator('.metricValue')).toHaveText(/\d+\s*(runs)?/);

    // 4. Project and pipeline selection
    const projectSelect = page.getByRole('combobox', { name: /Project/i }).or(page.getByTestId('project-select'));
    const pipelineSelect = page.getByRole('combobox', { name: /Pipeline/i }).or(page.getByTestId('pipeline-select'));

    await expect(async () => {
      const pCount = await projectSelect.locator('option').count();
      expect(pCount).toBeGreaterThan(1);
    }).toPass({ timeout: 20_000 });

    const projectOptions = await projectSelect.locator('option').allTextContents();
    const targetProject = projectOptions.includes('project-1') ? 'project-1' : projectOptions[1];
    await projectSelect.selectOption({ label: targetProject });

    await expect(async () => {
      const pipeCount = await pipelineSelect.locator('option').count();
      expect(pipeCount).toBeGreaterThan(1);
    }).toPass({ timeout: 20_000 });

    const pipelineOptions = await pipelineSelect.locator('option').allTextContents();
    const targetPipeline = pipelineOptions.find(o => o.includes('pipeline-1')) || pipelineOptions[1];

    // Selecting a pipeline triggers a new summary request with pipeline_id
    const pipelineSummaryPromise = page.waitForResponse(
      res => res.url().includes('/api/v1/summary') && res.url().includes('pipeline_id=') && res.status() === 200,
      { timeout: 35_000 }
    );
    await pipelineSelect.selectOption({ label: targetPipeline });
    await pipelineSummaryPromise;

    // Verify metric is populated for selected pipeline
    await expect(completedRuns.locator('.metricValue')).toHaveText(/\d+\s*(runs)?/);

    // 5. Set up network synchronization for the second summary request before initiating reload
    const reloadSummaryPromise = page.waitForResponse(
      res => res.url().includes('/api/v1/summary') && res.url().includes('days=90') && res.status() === 200,
      { timeout: 35_000 }
    );

    const reloadResponse = await page.reload();
    expect(reloadResponse?.status()).toBe(200);

    // 6. The second summary API completes successfully
    await reloadSummaryPromise;

    // 7. Verify Completed Runs contains a numeric value again
    await expect(completedRuns).toBeVisible();
    await expect(completedRuns.locator('.metricValue')).toHaveText(/\d+\s*(runs)?/);

    // 8. Verify Build Average Duration contains a valid duration
    const avgDuration = page.locator('.metric').filter({ hasText: 'Build Average Duration' }).or(page.getByTestId('build-average-duration'));
    await expect(avgDuration).toBeVisible();
    await expect(avgDuration.locator('.metricValue')).toHaveText(/\d+(s|m)/);

    // 9. Verify no fatal error state exists and controls remain functional
    const errorBox = page.locator('.errorBox');
    await expect(errorBox).not.toBeVisible();
    await expect(status).toContainText('CONNECTED');
    await expect(projectSelect).toBeEnabled();
    await expect(pipelineSelect).toBeEnabled();
  });
});
