import type { EChartsOption } from 'echarts'
import {
  EARLIER_LABEL,
  OTHER_AREAS_LABEL,
  isCatchAll,
  monthLabel,
  personSeries,
  type AlertAnalysis,
  type AreaRow,
  type BugAnalysis,
  type BugRow,
  type SprintBar,
} from './workItemInsights'

export type ChartTheme = 'dark' | 'light'

const PALETTE = ['#6366f1', '#22c55e', '#f59e0b', '#06b6d4', '#ec4899', '#a855f7', '#84cc16', '#f97316', '#14b8a6', '#ef4444']
const MUTED_SERIES = '#71717a'
export const STATE_COLORS = { backlog: '#f59e0b', active: '#6366f1', closed: '#22c55e' }
export const ALERT_COLORS = { open: '#f59e0b', closed: '#22c55e' }

const isMuted = (name: string) => isCatchAll(name) || name === 'Others' || name === OTHER_AREAS_LABEL
const colorsFor = (names: string[]) => {
  let next = 0
  return names.map(name => (isMuted(name) ? MUTED_SERIES : PALETTE[next++ % PALETTE.length]))
}

function look(theme: ChartTheme) {
  const dark = theme === 'dark'
  return {
    axis: dark ? '#a1a1aa' : '#475569',
    grid: dark ? '#2e2f38' : '#e2e8f0',
    legend: dark ? '#d4d4d8' : '#334155',
    tooltip: {
      backgroundColor: dark ? '#18181b' : '#ffffff',
      borderColor: dark ? '#3f3f46' : '#cbd5e1',
      textStyle: { color: dark ? '#f4f4f5' : '#0f172a', fontSize: 12 },
    },
  }
}

const sum = (values: Array<number | undefined>) => values.reduce<number>((a, b) => a + (b ?? 0), 0)

/** Names come from Azure DevOps and from the AI, so they are escaped before they go into tooltip HTML. */
export const escapeHtml = (text: string) =>
  String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')

/** A tooltip listing the non-zero series of a stack and its total. */
function stackTooltip(theme: ChartTheme) {
  return {
    trigger: 'axis' as const,
    axisPointer: { type: 'shadow' as const },
    ...look(theme).tooltip,
    formatter: (raw: unknown) => {
      const rows = (raw as Array<{ axisValueLabel: string; marker: string; seriesName: string; value: number }>).filter(r => r.value > 0 && r.seriesName !== 'Total')
      if (!rows.length) return ''
      const lines = rows.map(r => `${r.marker} ${escapeHtml(r.seriesName)}: <b>${r.value}</b>`)
      return `${escapeHtml(rows[0].axisValueLabel)}<br/>${lines.join('<br/>')}<br/><b>Total: ${sum(rows.map(r => r.value))}</b>`
    },
  }
}

function columnAxes(theme: ChartTheme, labels: string[], rotate: boolean) {
  const t = look(theme)
  return {
    xAxis: {
      type: 'category' as const,
      data: labels,
      axisLabel: { color: t.axis, interval: 0, rotate: rotate ? 35 : 0 },
      axisLine: { lineStyle: { color: t.grid } },
    },
    yAxis: { type: 'value' as const, minInterval: 1, axisLabel: { color: t.axis }, splitLine: { lineStyle: { color: t.grid } } },
  }
}

/** Width in pixels of the label column of a horizontal bar chart: as wide as the longest label, within limits. */
export const labelColumnWidth = (labels: string[]) => Math.min(240, Math.max(90, Math.max(0, ...labels.map(l => l.length)) * 6.8 + 8))

function barAxes(theme: ChartTheme, labels: string[]) {
  const t = look(theme)
  return {
    yAxis: { type: 'category' as const, data: labels, inverse: true, axisLabel: { color: t.axis, width: labelColumnWidth(labels), overflow: 'truncate' as const }, axisLine: { lineStyle: { color: t.grid } } },
    xAxis: { type: 'value' as const, minInterval: 1, axisLabel: { color: t.axis }, splitLine: { lineStyle: { color: t.grid } } },
  }
}

const barGrid = (labels: string[], top: number) => ({ left: labelColumnWidth(labels) + 12, right: 44, top, bottom: 8, containLabel: false })

/** Height in pixels for a horizontal bar chart with this many rows. */
export const barChartHeight = (rows: number) => Math.max(240, rows * 30 + 70)

/** An invisible stacked series that prints the total at the end of each horizontal bar. */
const totalLabels = (totals: number[], theme: ChartTheme, stack: string) => ({
  name: 'Total', type: 'bar' as const, stack, silent: true, itemStyle: { color: 'transparent' }, tooltip: { show: false },
  label: { show: true, position: 'right' as const, color: look(theme).axis, fontSize: 11, formatter: (p: { dataIndex: number }) => String(totals[p.dataIndex]) },
  data: totals.map(() => 0),
})

// ---------------------------------------------------------------- section 1

export function closedBySprintOption(bars: SprintBar[], theme: ChartTheme): EChartsOption {
  const t = look(theme)
  const series = personSeries(bars)
  const colors = colorsFor(series.map(s => s.name))
  return {
    color: colors,
    tooltip: stackTooltip(theme),
    legend: { type: 'scroll', top: 0, textStyle: { color: t.legend } },
    grid: { left: 44, right: 16, top: 44, bottom: bars.length > 14 ? 78 : 44, containLabel: true },
    ...columnAxes(theme, bars.map(b => b.label), bars.length > 8),
    dataZoom: bars.length > 14 ? [{ type: 'slider', height: 18, bottom: 6 }] : [],
    series: series.map(s => ({ name: s.name, type: 'bar' as const, stack: 'closed', barMaxWidth: 46, emphasis: { focus: 'series' as const }, data: s.data })),
  }
}

// ---------------------------------------------------------------- section 2

export function areaOptions(rows: AreaRow[], theme: ChartTheme): EChartsOption {
  const t = look(theme)
  const part = (name: string, key: 'backlog' | 'active' | 'closed') => ({
    name, type: 'bar' as const, stack: 'items', barMaxWidth: 22, emphasis: { focus: 'series' as const }, itemStyle: { color: STATE_COLORS[key] }, data: rows.map(r => r[key]),
  })
  return {
    tooltip: stackTooltip(theme),
    legend: { top: 0, textStyle: { color: t.legend }, data: ['Backlog', 'Active', 'Closed'] },
    grid: barGrid(rows.map(r => r.area), 36),
    ...barAxes(theme, rows.map(r => r.area)),
    series: [part('Backlog', 'backlog'), part('Active', 'active'), part('Closed', 'closed'), totalLabels(rows.map(r => r.total), theme, 'items')],
  }
}

// ---------------------------------------------------------------- section 3

export function bugsByAreaOption(rows: BugRow[], theme: ChartTheme): EChartsOption {
  const t = look(theme)
  const part = (name: string, key: 'open' | 'closed', color: string) => ({
    name, type: 'bar' as const, stack: 'bugs', barMaxWidth: 22, emphasis: { focus: 'series' as const }, itemStyle: { color }, data: rows.map(r => r[key]),
  })
  return {
    tooltip: stackTooltip(theme),
    legend: { top: 0, textStyle: { color: t.legend }, data: ['Open', 'Closed'] },
    grid: barGrid(rows.map(r => r.area), 36),
    ...barAxes(theme, rows.map(r => r.area)),
    series: [part('Open', 'open', ALERT_COLORS.open), part('Closed', 'closed', ALERT_COLORS.closed), totalLabels(rows.map(r => r.total), theme, 'bugs')],
  }
}

export function bugsByMonthOption(analysis: BugAnalysis, theme: ChartTheme): EChartsOption {
  const t = look(theme)
  const colors = colorsFor(analysis.series.map(s => s.area))
  return {
    color: colors,
    tooltip: stackTooltip(theme),
    legend: { type: 'scroll', top: 0, textStyle: { color: t.legend } },
    grid: { left: 44, right: 16, top: 44, bottom: 40, containLabel: true },
    ...columnAxes(theme, analysis.months.map(monthLabel), false),
    series: analysis.series.map(s => ({ name: s.area, type: 'bar' as const, stack: 'bugs', barMaxWidth: 56, emphasis: { focus: 'series' as const }, data: s.counts })),
  }
}

// ---------------------------------------------------------------- section 4

export function alertsByMonthOption(analysis: AlertAnalysis, theme: ChartTheme): EChartsOption {
  const t = look(theme)
  const labels = analysis.buckets.map(b => (b === EARLIER_LABEL ? b : monthLabel(b)))
  const part = (name: string, color: string, data: number[]) => ({ name, type: 'bar' as const, stack: 'alerts', barMaxWidth: 56, itemStyle: { color }, data })
  return {
    tooltip: stackTooltip(theme),
    legend: { top: 0, textStyle: { color: t.legend }, data: ['Open', 'Closed'] },
    grid: { left: 44, right: 16, top: 44, bottom: 40, containLabel: true },
    ...columnAxes(theme, labels, false),
    series: [part('Open', ALERT_COLORS.open, analysis.openByBucket), part('Closed', ALERT_COLORS.closed, analysis.closedByBucket)],
  }
}

export function alertCategoriesOption(categories: { name: string; count: number }[], theme: ChartTheme): EChartsOption {
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...look(theme).tooltip },
    grid: barGrid(categories.map(c => c.name), 8),
    ...barAxes(theme, categories.map(c => c.name)),
    series: [{
      type: 'bar', barMaxWidth: 22, itemStyle: { color: PALETTE[0] }, data: categories.map(c => c.count),
      label: { show: true, position: 'right', color: look(theme).axis, fontSize: 11 },
    }],
  }
}
