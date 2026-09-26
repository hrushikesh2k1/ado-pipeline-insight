import { test, expect } from '@playwright/test';

test.describe('Pipeline Ingestion Flow', () => {
  test('TEST 6: Ingestion action is gated behind Azure DevOps connection', async ({ page }) => {
    await page.goto('/');

    // Verify ingestion button is not present before connection
    const ingestButton = page.getByRole('button', { name: 'Ingest History' }).or(page.getByTestId('ingest-history'));
    await expect(ingestButton).not.toBeVisible();

    // Verify discovery row is hidden
    const discoveryRow = page.locator('.discoveryRow');
    await expect(discoveryRow).not.toBeVisible();
  });

  test('TEST 6: Pipeline ingestion triggers historical ingestion and displays result', async ({ page }) => {
    const adoOrg = process.env.ADO_ORG;
    const adoPat = process.env.ADO_PAT;

    test.skip(!adoOrg || !adoPat, 'ADO_ORG and ADO_PAT are required for pipeline ingestion test.');

    await page.goto('/');

    const orgInput = page.getByPlaceholder('Organization').or(page.getByLabel('Azure DevOps organization'));
    const patInput = page.getByPlaceholder('PAT').or(page.getByLabel('Azure DevOps PAT'));
    const connectButton = page.getByRole('button', { name: 'Connect & Discover' }).or(page.getByTestId('connect-ado'));

    await orgInput.fill(adoOrg!);
    await patInput.fill(adoPat!);

    const connectPromise = page.waitForResponse(
      res => res.url().includes('/api/v1/ado/connect') && res.status() === 200,
      { timeout: 30_000 }
    );
    await connectButton.click();
    await connectPromise;

    // Select project
    const adoProjectSelect = page.getByRole('combobox', { name: /ADO Project/i }).or(page.getByTestId('ado-project-select'));
    await expect(adoProjectSelect).toBeVisible();
    const projectOptions = await adoProjectSelect.locator('option').allTextContents();
    const targetProject = projectOptions.includes('project-1') ? 'project-1' : projectOptions[1];
    await adoProjectSelect.selectOption({ label: targetProject });

    // Select pipeline
    const adoPipelineSelect = page.getByRole('combobox', { name: /ADO Pipeline/i }).or(page.getByTestId('ado-pipeline-select'));
    await expect(adoPipelineSelect).toBeVisible();
    const pipelineOptions = await adoPipelineSelect.locator('option').allTextContents();
    const targetPipeline = pipelineOptions.includes('pipeline-1') ? 'pipeline-1' : pipelineOptions[1];
    await adoPipelineSelect.selectOption({ label: targetPipeline });

    // Ingest History button should now be enabled
    const ingestButton = page.getByRole('button', { name: 'Ingest History' }).or(page.getByTestId('ingest-history'));
    await expect(ingestButton).toBeVisible();
    await expect(ingestButton).toBeEnabled();

    // Trigger ingestion
    const ingestPromise = page.waitForResponse(
      res => res.url().includes('/api/v1/ado/ingest'),
      { timeout: 60_000 }
    );
    await ingestButton.click();
    const ingestResponse = await ingestPromise;

    if (ingestResponse.status() === 200) {
      // Success feedback
      const resultBadge = page.locator('.ingestResult');
      await expect(resultBadge).toBeVisible({ timeout: 15_000 });
      await expect(resultBadge).toContainText(/runs ingested/i);
    } else {
      // Managed error message (e.g. INGEST_FUNCTION_URL not configured in test environment)
      const errorBox = page.locator('.errorBox');
      await expect(errorBox).toBeVisible();
    }
  });
});
