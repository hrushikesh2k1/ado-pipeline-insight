import { test, expect } from '@playwright/test';

test.describe('Window Selection Regression', () => {
  test('TEST 5: Window selector updates time range and triggers data refresh', async ({ page }) => {
    await page.goto('/');

    const windowSelect = page.getByRole('combobox', { name: /Window/i }).or(page.getByTestId('window-select'));
    await expect(windowSelect).toBeVisible();

    // Verify default selection represents Last 3 Months (value '90')
    const defaultValue = await windowSelect.inputValue();
    expect(defaultValue).toBe('90');

    // 1. Change to "Last 1 Month" (value 30)
    const req1Promise = page.waitForResponse(
      res => res.url().includes('/api/v1/summary') && res.url().includes('days=30') && res.status() === 200,
      { timeout: 30_000 }
    );
    await windowSelect.selectOption({ label: 'Last 1 Month' });
    await req1Promise;

    // Verify UI reflects selection
    expect(await windowSelect.inputValue()).toBe('30');

    // Verify metric cards remain populated and valid
    const completedRuns = page.locator('.metric').filter({ hasText: 'Completed Runs' }).or(page.getByTestId('completed-runs'));
    await expect(completedRuns.locator('.metricValue')).toHaveText(/\d+\s*(runs)?/);

    // 2. Change to "Last 6 Months" (value 180)
    const req2Promise = page.waitForResponse(
      res => res.url().includes('/api/v1/summary') && res.url().includes('days=180') && res.status() === 200,
      { timeout: 30_000 }
    );
    await windowSelect.selectOption({ label: 'Last 6 Months' });
    await req2Promise;

    expect(await windowSelect.inputValue()).toBe('180');
    await expect(completedRuns.locator('.metricValue')).toHaveText(/\d+\s*(runs)?/);

    // 3. Revert back to "Last 3 Months" (value 90) - handled by React Query cache/network
    await windowSelect.selectOption({ label: 'Last 3 Months' });
    expect(await windowSelect.inputValue()).toBe('90');
    await expect(completedRuns.locator('.metricValue')).toHaveText(/\d+\s*(runs)?/);
  });
});
