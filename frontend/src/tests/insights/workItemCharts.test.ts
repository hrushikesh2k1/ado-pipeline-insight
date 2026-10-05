import { describe, expect, it } from 'vitest'
import {
  alertCategoriesOption,
  alertsByMonthOption,
  areaOptions,
  barChartHeight,
  bugsByAreaOption,
  bugsByMonthOption,
  closedBySprintOption,
  escapeHtml,
  labelColumnWidth,
} from '../../utils/workItemCharts'
import type { AlertAnalysis, AreaRow, BugAnalysis, SprintBar } from '../../utils/workItemInsights'

type Series = { name?: string; data?: number[]; stack?: string; itemStyle?: { color?: string } }
const seriesOf = (option: { series?: unknown }) => option.series as Series[]
const axisData = (axis: unknown) => (axis as { data: string[] }).data

const bars: SprintBar[] = [
  { sprint: 'S1', label: 'Sprint 1', total: 3, byPerson: { Asha: 2, Ben: 1 }, lastClosed: '2026-07-10' },
  { sprint: 'S2', label: 'Sprint 2', total: 1, byPerson: { Asha: 1 }, lastClosed: '2026-08-10' },
]

describe('chart options', () => {
  it('closed per sprint: one stacked series per person, in the same order as the sprints', () => {
    const option = closedBySprintOption(bars, 'dark')
    expect(axisData(option.xAxis)).toEqual(['Sprint 1', 'Sprint 2'])
    expect(seriesOf(option).map(s => [s.name, s.data, s.stack])).toEqual([['Asha', [2, 1], 'closed'], ['Ben', [1, 0], 'closed']])
  })

  it('a long list of sprints gets a scroll bar, a short one does not', () => {
    const many = Array.from({ length: 20 }, (_, n) => ({ ...bars[0], sprint: `S${n}`, label: `S${n}` }))
    expect((closedBySprintOption(many, 'dark').dataZoom as unknown[]).length).toBe(1)
    expect((closedBySprintOption(bars, 'dark').dataZoom as unknown[]).length).toBe(0)
  })

  it('areas: backlog, active and closed stacks plus a hidden series that prints the total', () => {
    const rows: AreaRow[] = [{ area: 'VPN', backlog: 1, active: 2, closed: 3, total: 6 }, { area: 'Other', backlog: 0, active: 1, closed: 0, total: 1 }]
    const option = areaOptions(rows, 'light')
    expect(axisData(option.yAxis)).toEqual(['VPN', 'Other'])
    expect(seriesOf(option).map(s => s.name)).toEqual(['Backlog', 'Active', 'Closed', 'Total'])
    expect(seriesOf(option)[1].data).toEqual([2, 1])
    expect(seriesOf(option)[3].data).toEqual([0, 0])
  })

  it('bugs by area: open and closed stacks', () => {
    const option = bugsByAreaOption([{ area: 'VPN', total: 3, open: 2, closed: 1 }], 'dark')
    expect(seriesOf(option).map(s => [s.name, s.data])).toEqual([['Open', [2]], ['Closed', [1]], ['Total', [0]]])
  })

  it('bugs by month: a series per area over the months, catch-all areas in grey', () => {
    const analysis: BugAnalysis = {
      total: 3, olderOpen: 0, rows: [], months: ['2026-08', '2026-09'],
      series: [{ area: 'VPN', counts: [1, 1] }, { area: 'Other', counts: [0, 1] }],
    }
    const option = bugsByMonthOption(analysis, 'dark')
    expect(axisData(option.xAxis)).toEqual(['Aug 2026', 'Sep 2026'])
    expect(seriesOf(option).map(s => s.name)).toEqual(['VPN', 'Other'])
    expect((option.color as string[])[1]).toBe('#71717a')
    expect((option.color as string[])[0]).not.toBe('#71717a')
  })

  it('alerts by month: Earlier first, then the months; open and closed', () => {
    const analysis: AlertAnalysis = { items: [], open: 1, closed: 2, buckets: ['Earlier', '2026-09'], openByBucket: [1, 0], closedByBucket: [0, 2], checked: true }
    const option = alertsByMonthOption(analysis, 'dark')
    expect(axisData(option.xAxis)).toEqual(['Earlier', 'Sep 2026'])
    expect(seriesOf(option).map(s => [s.name, s.data])).toEqual([['Open', [1, 0]], ['Closed', [0, 2]]])
  })

  it('alert categories: one bar per category', () => {
    const option = alertCategoriesOption([{ name: 'VPN', count: 3 }, { name: 'AKS', count: 2 }], 'dark')
    expect(axisData(option.yAxis)).toEqual(['VPN', 'AKS'])
    expect(seriesOf(option)[0].data).toEqual([3, 2])
  })

  it('a horizontal chart grows with its rows but never gets tiny', () => {
    expect(barChartHeight(1)).toBe(240)
    expect(barChartHeight(20)).toBe(670)
  })

  it('names are escaped before they go into tooltip HTML', () => {
    expect(escapeHtml(`<img src=x onerror="alert('x')">&`)).toBe('&lt;img src=x onerror=&quot;alert(&#39;x&#39;)&quot;&gt;&amp;')
    const hostile: SprintBar[] = [{ sprint: 'S1', label: 'Sprint 1', total: 1, byPerson: { '<img src=x onerror=alert(1)>': 1 }, lastClosed: '2026-07-10' }]
    const tooltip = closedBySprintOption(hostile, 'dark').tooltip as { formatter: (p: unknown) => string }
    const html = tooltip.formatter([{ axisValueLabel: '<b>Sprint 1</b>', marker: '<span></span>', seriesName: '<img src=x onerror=alert(1)>', value: 1 }])
    expect(html).not.toContain('<img')
    expect(html).not.toContain('<b>Sprint')
    expect(html).toContain('&lt;img src=x onerror=alert(1)&gt;')
  })

  it('the label column fits the longest area name, within limits, so no name is clipped', () => {
    expect(labelColumnWidth(['Login and authentication'])).toBeGreaterThan('Login and authentication'.length * 6)
    expect(labelColumnWidth(['VPN'])).toBe(90)
    expect(labelColumnWidth(['x'.repeat(200)])).toBe(240)
    expect(labelColumnWidth([])).toBe(90)
  })
})
