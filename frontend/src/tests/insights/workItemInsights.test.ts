import { describe, expect, it } from 'vitest'
import type { InsightItem } from '../../types/api'
import {
  EARLIER_LABEL,
  OTHER_AREAS_LABEL,
  alertScope,
  areaSummary,
  bugsByArea,
  closedBySprint,
  closers,
  monthLabel,
  personSeries,
  sprintLabels,
  windowMonths,
  workItemUrl,
} from '../../utils/workItemInsights'

let nextId = 1
const item = (over: Partial<InsightItem> = {}): InsightItem => ({
  id: nextId++, type: 'Bug', title: 'x', state: 'Active', state_category: 'inprogress', assigned_to: 'Asha',
  created: '2026-09-10T08:00:00Z', closed: null, sprint: 'Sprint 5', area_path: 'P\\Mon', area: 'VPN', alert_work: null, ...over,
})
const closed = (over: Partial<InsightItem> = {}) => item({ state: 'Closed', state_category: 'completed', closed: '2026-09-20T08:00:00Z', ...over })

describe('months', () => {
  it('the window is the months back from now plus the current one', () => {
    expect(windowMonths(new Date('2026-10-05T12:00:00Z'), 6)).toEqual(['2026-04', '2026-05', '2026-06', '2026-07', '2026-08', '2026-09', '2026-10'])
  })
  it('crosses the year boundary', () => {
    expect(windowMonths(new Date('2026-02-01T00:00:00Z'), 3)).toEqual(['2025-11', '2025-12', '2026-01', '2026-02'])
  })
  it('labels a month for people', () => {
    expect(monthLabel('2026-09')).toBe('Sep 2026')
    expect(monthLabel('weird')).toBe('weird')
  })
})

describe('sprint labels', () => {
  it('shows the last part of the path', () => {
    expect(sprintLabels(['2026\\Sprint 5', '2026\\Sprint 6'])).toEqual({ '2026\\Sprint 5': 'Sprint 5', '2026\\Sprint 6': 'Sprint 6' })
  })
  it('shows the whole path when two sprints share a name', () => {
    expect(sprintLabels(['2025\\Sprint 1', '2026\\Sprint 1', 'Sprint 2'])).toEqual({
      '2025\\Sprint 1': '2025 › Sprint 1', '2026\\Sprint 1': '2026 › Sprint 1', 'Sprint 2': 'Sprint 2',
    })
  })
})

describe('section 1: closed work per sprint, by person', () => {
  const items = [
    closed({ sprint: 'S1', assigned_to: 'Asha', closed: '2026-07-10T00:00:00Z' }),
    closed({ sprint: 'S1', assigned_to: 'Ben', closed: '2026-07-12T00:00:00Z' }),
    closed({ sprint: 'S2', assigned_to: 'Asha', closed: '2026-08-10T00:00:00Z' }),
    closed({ sprint: 'S2', assigned_to: 'Asha', type: 'Task', closed: '2026-08-11T00:00:00Z' }),
    item({ sprint: 'S2', assigned_to: 'Ben' }), // still open: never counted
    closed({ sprint: 'S0', assigned_to: 'Cy', closed: '2026-06-01T00:00:00Z' }),
  ]

  it('counts only closed work, oldest sprint first', () => {
    const bars = closedBySprint(items, { persons: [], types: [] })
    expect(bars.map(b => [b.sprint, b.total])).toEqual([['S0', 1], ['S1', 2], ['S2', 2]])
    expect(bars[1].byPerson).toEqual({ Asha: 1, Ben: 1 })
  })
  it('narrows to the chosen people', () => {
    const bars = closedBySprint(items, { persons: ['Asha'], types: [] })
    expect(bars.map(b => [b.sprint, b.total])).toEqual([['S1', 1], ['S2', 2]])
  })
  it('narrows to the chosen work item types', () => {
    const bars = closedBySprint(items, { persons: [], types: ['Task'] })
    expect(bars.map(b => [b.sprint, b.total])).toEqual([['S2', 1]])
  })
  it('lists who closed work, most first, for the person filter', () => {
    expect(closers(items)).toEqual([{ name: 'Asha', count: 3 }, { name: 'Ben', count: 1 }, { name: 'Cy', count: 1 }])
    expect(closers(items, ['Task'])).toEqual([{ name: 'Asha', count: 1 }])
  })
  it('an item marked closed without a closing date is not counted', () => {
    expect(closedBySprint([closed({ closed: null })], { persons: [], types: [] })).toEqual([])
  })
  it('a total of the bars equals the number of closed items', () => {
    const bars = closedBySprint(items, { persons: [], types: [] })
    expect(bars.reduce((s, b) => s + b.total, 0)).toBe(items.filter(i => i.state_category === 'completed').length)
  })

  describe('stacked series', () => {
    it('one series per person, aligned with the bars', () => {
      const bars = closedBySprint(items, { persons: [], types: [] })
      expect(personSeries(bars)).toEqual([
        { name: 'Asha', data: [0, 1, 2] },
        { name: 'Ben', data: [0, 1, 0] },
        { name: 'Cy', data: [1, 0, 0] },
      ])
    })
    it('many people are folded into Others, and nothing is lost', () => {
      const many = Array.from({ length: 15 }, (_, n) => closed({ sprint: 'S1', assigned_to: `P${String(n).padStart(2, '0')}` }))
      const series = personSeries(closedBySprint(many, { persons: [], types: [] }), 10)
      expect(series).toHaveLength(10)
      expect(series[9]).toEqual({ name: 'Others', data: [6] })
      expect(series.reduce((s, x) => s + x.data[0], 0)).toBe(15)
    })
  })
})

describe('section 2: work items by area', () => {
  const items = [
    item({ area: 'VPN', state_category: 'proposed' }),
    item({ area: 'VPN', state_category: 'inprogress' }),
    item({ area: 'VPN', state_category: 'resolved' }),
    closed({ area: 'VPN' }),
    closed({ area: 'Login' }),
    item({ area: 'Other', state_category: 'proposed' }),
    item({ area: 'Other', state_category: 'proposed' }),
    item({ area: 'Other', state_category: 'proposed' }),
    item({ area: 'Other', state_category: 'proposed' }),
    item({ area: 'Login', type: 'Task', state_category: 'proposed' }),
  ]

  it('splits each area into backlog, active and closed', () => {
    expect(areaSummary(items).find(r => r.area === 'VPN')).toEqual({ area: 'VPN', backlog: 1, active: 2, closed: 1, total: 4 })
  })
  it('lists the biggest real area first and the catch-all area last, however big it is', () => {
    expect(areaSummary(items).map(r => r.area)).toEqual(['VPN', 'Login', 'Other'])
  })
  it('can be narrowed to some types', () => {
    expect(areaSummary(items, ['Task'])).toEqual([{ area: 'Login', backlog: 1, active: 0, closed: 0, total: 1 }])
  })
  it('every item is counted exactly once', () => {
    expect(areaSummary(items).reduce((s, r) => s + r.total, 0)).toBe(items.length)
  })
})

describe('section 3: bugs by area', () => {
  const months = ['2026-08', '2026-09', '2026-10']
  const bugs = [
    item({ area: 'VPN', created: '2026-08-02T00:00:00Z' }),
    item({ area: 'VPN', created: '2026-09-02T00:00:00Z' }),
    closed({ area: 'VPN', created: '2026-09-03T00:00:00Z' }),
    item({ area: 'AKS', created: '2026-10-01T00:00:00Z' }),
    item({ area: 'Other', created: '2026-10-02T00:00:00Z' }),
    item({ area: 'VPN', created: '2025-01-01T00:00:00Z' }), // open, raised long before the window
    closed({ area: 'VPN', created: '2025-01-01T00:00:00Z' }), // closed, raised long before the window
    item({ area: 'VPN', type: 'Task', created: '2026-09-02T00:00:00Z' }), // not a bug
  ]

  it('counts the bugs raised inside the window, by area, split into open and closed', () => {
    const result = bugsByArea(bugs, ['Bug'], months)
    expect(result.total).toBe(5)
    expect(result.rows).toEqual([
      { area: 'VPN', total: 3, open: 2, closed: 1 },
      { area: 'AKS', total: 1, open: 1, closed: 0 },
      { area: 'Other', total: 1, open: 1, closed: 0 },
    ])
  })
  it('does not count other work item types', () => {
    expect(bugsByArea(bugs, ['Bug'], months).total).toBe(5)
    expect(bugsByArea(bugs, ['Bug', 'Task'], months).total).toBe(6)
    expect(bugsByArea(bugs, [], months).total).toBe(0)
  })
  it('says how many open bugs were raised before the window instead of hiding them', () => {
    expect(bugsByArea(bugs, ['Bug'], months).olderOpen).toBe(1)
  })
  it('gives a series per area with a count for every month', () => {
    expect(bugsByArea(bugs, ['Bug'], months).series).toEqual([
      { area: 'VPN', counts: [1, 2, 0] },
      { area: 'AKS', counts: [0, 0, 1] },
      { area: 'Other', counts: [0, 0, 1] },
    ])
  })
  it('rolls small areas into one series so the chart stays readable, without losing a bug', () => {
    const many = Array.from({ length: 12 }, (_, n) => item({ area: `Area ${String(n).padStart(2, '0')}`, created: '2026-09-02T00:00:00Z' }))
    const result = bugsByArea(many, ['Bug'], months, 5)
    expect(result.series.map(s => s.area)).toEqual(['Area 00', 'Area 01', 'Area 02', 'Area 03', 'Area 04', OTHER_AREAS_LABEL]) // ties break by name
    expect(result.series.reduce((s, x) => s + x.counts.reduce((a, b) => a + b, 0), 0)).toBe(12)
    expect(result.rows).toHaveLength(12) // the by-area ranking still lists every area
  })
  it('no bugs means empty results, not an error', () => {
    expect(bugsByArea([], ['Bug'], months)).toEqual({ total: 0, olderOpen: 0, rows: [], months, series: [] })
  })
})

describe('section 4: alert scope', () => {
  const months = ['2026-08', '2026-09']
  const items = [
    item({ alert_work: true, created: '2026-08-05T00:00:00Z' }),
    closed({ alert_work: true, created: '2026-08-06T00:00:00Z' }),
    closed({ alert_work: true, created: '2026-09-06T00:00:00Z' }),
    item({ alert_work: true, created: '2025-02-01T00:00:00Z' }),
    item({ alert_work: false }),
    item({ alert_work: null }),
  ]

  it('counts only the work items the AI says build alerts, open and closed', () => {
    const result = alertScope(items, months)
    expect(result.items).toHaveLength(4)
    expect({ open: result.open, closed: result.closed }).toEqual({ open: 2, closed: 2 })
  })
  it('groups them by the month they were raised, with older ones in Earlier', () => {
    const result = alertScope(items, months)
    expect(result.buckets).toEqual([EARLIER_LABEL, '2026-08', '2026-09'])
    expect(result.openByBucket).toEqual([1, 1, 0])
    expect(result.closedByBucket).toEqual([0, 1, 1])
  })
  it('says whether the question was ever asked', () => {
    expect(alertScope(items, months).checked).toBe(true)
    expect(alertScope([item({ alert_work: null })], months).checked).toBe(false)
    expect(alertScope([], months).checked).toBe(false)
  })
})

describe('links', () => {
  it('links a work item in Azure DevOps, escaping the names', () => {
    expect(workItemUrl('my org', 'Proj A', 42)).toBe('https://dev.azure.com/my%20org/Proj%20A/_workitems/edit/42')
  })
})
