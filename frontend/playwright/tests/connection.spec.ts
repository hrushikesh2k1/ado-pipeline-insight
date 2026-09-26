import { test, expect } from '@playwright/test';

test.describe('Azure DevOps Connection & Discovery Flow', () => {
  test('TEST 3: Connection UI elements, password masking, and client validation', async ({ page }) => {
    await page.goto('/');

    // 1. Verify Connect Azure DevOps section
    const connectHeading = page.getByRole('heading', { name: 'Connect Azure DevOps' });
    await expect(connectHeading).toBeVisible();

    // 2. Verify Organization input
    const orgInput = page.getByPlaceholder('Organization').or(page.getByLabel('Azure DevOps organization'));
    await expect(orgInput).toBeVisible();

    // 3. Verify PAT input and password masking (type="password")
    const patInput = page.getByPlaceholder('PAT').or(page.getByLabel('Azure DevOps PAT'));
    await expect(patInput).toBeVisible();
    await expect(patInput).toHaveAttribute('type', 'password');

    // 4. Verify Connect & Discover button
    const connectButton = page.getByRole('button', { name: 'Connect & Discover' }).or(page.getByTestId('connect-ado'));
    await expect(connectButton).toBeVisible();

    // 5. Client validation: button disabled when fields are empty
    await expect(connectButton).toBeDisabled();

    // Fill only Org -> still disabled
    await orgInput.fill('test-org');
    await expect(connectButton).toBeDisabled();

    // Fill only PAT (clear Org) -> still disabled
    await orgInput.fill('');
    await patInput.fill('dummy-pat');
    await expect(connectButton).toBeDisabled();

    // Both filled -> button becomes enabled
    await orgInput.fill('test-org');
    await expect(connectButton).toBeEnabled();
  });

  test('TEST 3 (Negative): Invalid ADO credentials display controlled error without crashing', async ({ page }) => {
    await page.goto('/');

    const orgInput = page.getByPlaceholder('Organization').or(page.getByLabel('Azure DevOps organization'));
    const patInput = page.getByPlaceholder('PAT').or(page.getByLabel('Azure DevOps PAT'));
    const connectButton = page.getByRole('button', { name: 'Connect & Discover' }).or(page.getByTestId('connect-ado'));

    await orgInput.fill('invalid-org-nonexistent');
    await patInput.fill('invalid-pat-sample');

    // Listen for the API response
    const responsePromise = page.waitForResponse(
      res => res.url().includes('/api/v1/ado/connect'),
      { timeout: 20_000 }
    );

    await connectButton.click();
    const response = await responsePromise;
    expect([401, 403, 502, 503]).toContain(response.status());

    // Verify error banner is displayed cleanly
    const errorBox = page.locator('.connectError');
    await expect(errorBox).toBeVisible();
    await expect(errorBox).toContainText(/Azure DevOps (returned HTTP|connection|authentication)/i);

    // Verify application remains interactive
    await expect(page.getByRole('heading', { name: 'ADO Pipeline Insight' })).toBeVisible();
    await expect(connectButton).toBeEnabled();
  });

  test('TEST 4: Azure DevOps discovery populates projects and pipelines with valid credentials', async ({ page }) => {
    const adoOrg = process.env.ADO_ORG;
    const adoPat = process.env.ADO_PAT;

    test.skip(!adoOrg || !adoPat, 'ADO_ORG and ADO_PAT are required for this test.');

    await page.goto('/');

    const orgInput = page.getByPlaceholder('Organization').or(page.getByLabel('Azure DevOps organization'));
    const patInput = page.getByPlaceholder('PAT').or(page.getByLabel('Azure DevOps PAT'));
    const connectButton = page.getByRole('button', { name: 'Connect & Discover' }).or(page.getByTestId('connect-ado'));

    await orgInput.fill(adoOrg!);
    await patInput.fill(adoPat!);

    const responsePromise = page.waitForResponse(
      res => res.url().includes('/api/v1/ado/connect') && res.status() === 200,
      { timeout: 30_000 }
    );

    await connectButton.click();
    await responsePromise;

    // Verify discovery row appears
    const discoveryRow = page.locator('.discoveryRow');
    await expect(discoveryRow).toBeVisible();

    // Verify ADO Project selector is populated
    const adoProjectSelect = page.getByRole('combobox', { name: /ADO Project/i }).or(page.getByTestId('ado-project-select'));
    await expect(adoProjectSelect).toBeVisible();

    // Check project options
    const projectOptions = await adoProjectSelect.locator('option').allTextContents();
    expect(projectOptions.length).toBeGreaterThan(1);

    // Select project-1 if present, otherwise first discovered project
    const targetProject = projectOptions.includes('project-1') ? 'project-1' : projectOptions[1];
    await adoProjectSelect.selectOption({ label: targetProject });

    // Verify ADO Pipeline selector populated
    const adoPipelineSelect = page.getByRole('combobox', { name: /ADO Pipeline/i }).or(page.getByTestId('ado-pipeline-select'));
    await expect(adoPipelineSelect).toBeVisible();

    const pipelineOptions = await adoPipelineSelect.locator('option').allTextContents();
    expect(pipelineOptions.length).toBeGreaterThan(1);

    const targetPipeline = pipelineOptions.includes('pipeline-1') ? 'pipeline-1' : pipelineOptions[1];
    await adoPipelineSelect.selectOption({ label: targetPipeline });
  });
});
