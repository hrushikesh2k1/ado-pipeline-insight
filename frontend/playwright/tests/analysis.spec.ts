import { test, expect } from '@playwright/test';

test.describe('AI Optimization & Pipeline Analysis Flow', () => {
  test('TEST 7: AI recommendations panel states and structural validation', async ({ page }) => {
    await page.goto('/');

    // 1. Verify AI Recommendations panel exists
    const aiPanel = page.getByRole('heading', { name: 'AI Optimization Recommendations' });
    await expect(aiPanel).toBeVisible();

    const analyzeButton = page.getByRole('button', { name: /Run AI Analysis|Analyzing/i }).or(page.getByTestId('run-ai-analysis'));
    await expect(analyzeButton).toBeVisible();

    // 2. When no pipeline is selected, button is disabled and placeholder prompt is shown
    await expect(analyzeButton).toBeDisabled();
    await expect(page.getByText('Select a pipeline to view AI findings.')).toBeVisible();

    // 3. Wait for options to be populated from /api/v1/options
    const pipelineSelect = page.getByRole('combobox', { name: /Pipeline/i }).or(page.getByTestId('pipeline-select'));
    await expect(async () => {
      const count = await pipelineSelect.locator('option').count();
      expect(count).toBeGreaterThan(1);
    }).toPass({ timeout: 20_000 });

    const options = await pipelineSelect.locator('option').allTextContents();
    const targetPipeline = options.find(o => o.includes('pipeline-1')) || options[1];

    // Wait for the recommendations API call triggered when pipeline is selected
    const recsPromise = page.waitForResponse(
      res => res.url().includes('/recommendations') && res.status() === 200,
      { timeout: 30_000 }
    );

    await pipelineSelect.selectOption({ label: targetPipeline });
    await recsPromise;

    // 4. Verify the "Run AI Analysis" button becomes enabled
    await expect(analyzeButton).toBeEnabled();

    // 5. Verify recommendation findings structure if findings are present
    const findings = page.locator('.finding');
    const count = await findings.count();

    if (count > 0) {
      // Validate structural elements of the first recommendation
      const firstFinding = findings.first();
      await expect(firstFinding.locator('.severity')).toBeVisible();
      await expect(firstFinding.locator('b')).toBeVisible(); // Stage / Task title
      await expect(firstFinding.locator('p')).toBeVisible(); // Recommendation description
      await expect(firstFinding.locator('small')).toBeVisible(); // Evidence / metrics backing

      // Verify severity is one of the supported standard levels
      const severityText = await firstFinding.locator('.severity').textContent();
      expect(['HIGH', 'MEDIUM', 'LOW', 'CRITICAL', 'INFO']).toContain(severityText?.trim().toUpperCase());
    } else {
      // If no pre-stored recommendations exist, verify valid empty-state messaging
      await expect(
        page.getByText(/No optimization findings detected|Loading recommendations/i)
      ).toBeVisible();
    }
  });

  test('TEST 7: Triggering AI analysis sends structured request and returns valid model', async ({ page }) => {
    await page.goto('/');

    const pipelineSelect = page.getByRole('combobox', { name: /Pipeline/i }).or(page.getByTestId('pipeline-select'));
    
    // Wait for options to populate
    await expect(async () => {
      const count = await pipelineSelect.locator('option').count();
      expect(count).toBeGreaterThan(1);
    }).toPass({ timeout: 20_000 });

    const options = await pipelineSelect.locator('option').allTextContents();
    const targetPipeline = options.find(o => o.includes('pipeline-1')) || options[1];

    await pipelineSelect.selectOption({ label: targetPipeline });

    const analyzeButton = page.getByRole('button', { name: /Run AI Analysis|Analyzing/i }).or(page.getByTestId('run-ai-analysis'));
    await expect(analyzeButton).toBeEnabled();

    // Trigger analysis and verify endpoint response
    const analyzePromise = page.waitForResponse(
      res => res.url().includes('/analyze'),
      { timeout: 45_000 }
    );

    await analyzeButton.click();
    const response = await analyzePromise;

    // Status can be 200 (analysis succeeded) or 503 (e.g. if OpenAI endpoint requires Azure Managed Identity)
    if (response.status() === 200) {
      const data = await response.json();
      expect(data).toHaveProperty('findings');
      expect(Array.isArray(data.findings)).toBe(true);

      // Verify rendered finding in DOM
      if (data.findings.length > 0) {
        const firstFinding = page.locator('.finding').first();
        await expect(firstFinding.locator('.severity')).toBeVisible();
        await expect(firstFinding.locator('b')).toBeVisible();
        await expect(firstFinding.locator('p')).toBeVisible();
      }
    } else {
      // Verify graceful error UI handling rather than unhandled white screen
      const errorOrEmpty = page.locator('.errorBox, .empty');
      await expect(errorOrEmpty.first()).toBeVisible();
    }

    // Application remains responsive
    await expect(page.getByRole('heading', { name: 'ADO Pipeline Insight' })).toBeVisible();
  });
});
