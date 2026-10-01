import { test, expect, Page } from '@playwright/test';
import { formatSeconds as fmt } from '../../src/utils';

/**
 * Data accuracy: what the dashboard DISPLAYS must equal what the API RETURNED to the page.
 * The API's own correctness is verified by quality_gate/functional_tests; this closes the last gap (API -> screen).
 */

type Captured = { summary: any[]; runs: any[]; trends: any[]; analysis: any[] };

function capture(page: Page): Captured {
  const seen: Captured = { summary: [], runs: [], trends: [], analysis: [] };
  page.on('response', async res => {
    if (res.status() !== 200) return;
    const url = res.url();
    try {
      if (url.includes('/api/v1/summary')) seen.summary.push(await res.json());
      else if (/\/api\/v1\/runs\?/.test(url)) seen.runs.push(await res.json());
      else if (url.includes('/api/v1/trends')) seen.trends.push(await res.json());
      else if (/\/api\/v1\/runs\/\d+\/analysis/.test(url)) seen.analysis.push(await res.json());
    } catch {
      /* body not available (navigation/abort) */
    }
  });
  return seen;
}

async function loadDashboard(page: Page): Promise<Captured> {
  const seen = capture(page);
  await page.goto('/');
  await page.waitForLoadState('networkidle', { timeout: 60_000 });
  await expect(page.locator('.metric').filter({ hasText: 'Completed Runs' }).locator('.metricValue')).toHaveText(/\d+\s*runs/, { timeout: 60_000 });
  expect(seen.summary.length, 'summary was never fetched').toBeGreaterThan(0);
  expect(seen.runs.length, 'runs were never fetched').toBeGreaterThan(0);
  expect(seen.trends.length, 'trends were never fetched').toBeGreaterThan(0);
  return seen;
}

const last = <T,>(items: T[]): T => items[items.length - 1];
const card = (page: Page, label: string) => page.locator('.metric').filter({ hasText: label });

test.describe('Dashboard shows exactly what the API returned', () => {
  test('summary cards match the summary response', async ({ page }) => {
    const seen = await loadDashboard(page);
    const s = last(seen.summary);
    await expect(card(page, 'Completed Runs').locator('.metricValue')).toHaveText(new RegExp(`^${s.total_runs}\\s*runs`));
    await expect(card(page, 'Successful Runs').locator('.metricValue')).toHaveText(new RegExp(`^${s.successful_runs}\\s*runs`));
    await expect(card(page, 'Failed Runs').locator('.metricValue')).toHaveText(new RegExp(`^${s.failed_runs}\\s*runs`));
    await expect(card(page, 'Successful Runs').locator('.metricSub')).toHaveText(`Pass rate ${s.success_rate_pct}%`);
    await expect(card(page, 'Failed Runs').locator('.metricSub')).toHaveText(`Failure rate ${s.failure_rate_pct}%`);
    await expect(card(page, 'Build Average Duration').locator('.metricValue')).toHaveText(fmt(s.average_duration_seconds));
    await expect(card(page, 'Build Average Duration').locator('.metricSub')).toHaveText(`P90 ${fmt(s.p90_duration_seconds)}`);
    await expect(card(page, 'Average Queue Time').locator('.metricValue')).toHaveText(fmt(s.average_queue_seconds));
  });

  test('build duration trend tabs show the number of runs and days the API returned', async ({ page }) => {
    const seen = await loadDashboard(page);
    const t = last(seen.trends);
    await expect(page.getByRole('button', { name: `Every Run (${t.build_trend.length})` })).toBeVisible();
    await expect(page.getByRole('button', { name: `Daily Average (${t.daily_trend.length})` })).toBeVisible();
    expect(t.build_trend.length, 'trend and run list disagree on the number of runs').toBe(last(seen.runs).total_count);
  });

  test('recent runs list shows the API runs in the same order with correct fields', async ({ page }) => {
    const seen = await loadDashboard(page);
    const r = last(seen.runs);
    await expect(page.getByRole('heading', { name: `Recent Runs (${r.items.length})` })).toBeVisible();
    const rows = page.locator('.runs .run');
    await expect(rows).toHaveCount(r.items.length);
    for (const [i, item] of r.items.slice(0, 10).entries()) {
      const row = rows.nth(i);
      await expect(row.locator('b')).toHaveText(`#${item.build_number || item.run_id}`);
      await expect(row.locator('span').first()).toHaveText(item.pipeline_name);
      await expect(row.locator('small')).toContainText(fmt(item.duration_seconds));
      await expect(row.locator('.result')).toHaveText(item.result || 'unknown');
    }
  });

  test('opening a run shows the same run and duration as the list', async ({ page }) => {
    const seen = await loadDashboard(page);
    const first = last(seen.runs).items[0];
    await page.locator('.runs .run').first().click();
    await expect(page.getByRole('heading', { name: `Run #${first.run_id}` })).toBeVisible({ timeout: 60_000 });
    const detail = last(seen.analysis);
    expect(detail.run.run_id).toBe(first.run_id);
    await expect(page.locator('.mini').filter({ hasText: 'Run duration' }).locator('b')).toHaveText(fmt(detail.metrics.run_duration_seconds));
    expect(detail.metrics.run_duration_seconds).toBe(first.duration_seconds);
  });
});
