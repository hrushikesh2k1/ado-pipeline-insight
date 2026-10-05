import type { InsightItem } from '../types/api'

/** Areas that are not real subjects; they are always listed last. */
const CATCH_ALL_AREAS = ['Other', 'Not grouped', '(project root)']
export const OTHER_AREAS_LABEL = 'Other areas'
export const EARLIER_LABEL = 'Earlier'
const MAX_SERIES = 10

export const isCatchAll = (area: string) => CATCH_ALL_AREAS.includes(area)

const byTotalThenCatchAll = <T extends { area: string; total: number }>(a: T, b: T) =>
  Number(isCatchAll(a.area)) - Number(isCatchAll(b.area)) || b.total - a.total || a.area.localeCompare(b.area)

// ---------------------------------------------------------------- months and sprints

export const monthKey = (iso: string | null | undefined): string => (iso ? iso.slice(0, 7) : '')

/** The months of the window as 'YYYY-MM' keys: `months` full months back, plus the current one (UTC, like the server). */
export function windowMonths(now: Date, months: number): string[] {
  const keys: string[] = []
  for (let back = months; back >= 0; back--) {
    const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - back, 1))
    keys.push(`${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`)
  }
  return keys
}

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
export function monthLabel(key: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(key)
  return match ? `${MONTH_NAMES[Number(match[2]) - 1]} ${match[1]}` : key
}

/** The last part of a sprint path, unless two sprints share it; then the whole path shows. */
export function sprintLabels(sprints: string[]): Record<string, string> {
  const leaf = (path: string) => path.split('\\').pop() || path
  const counts = new Map<string, number>()
  sprints.forEach(s => counts.set(leaf(s), (counts.get(leaf(s)) ?? 0) + 1))
  return Object.fromEntries(sprints.map(s => [s, (counts.get(leaf(s)) ?? 0) > 1 ? s.split('\\').join(' › ') : leaf(s)]))
}

// ---------------------------------------------------------------- section 1: closed per sprint, by person

export type ClosedFilters = { persons: string[]; types: string[] }
export type SprintBar = { sprint: string; label: string; total: number; byPerson: Record<string, number>; lastClosed: string }

export const isClosed = (item: InsightItem) => item.state_category === 'completed' && !!item.closed

/** People who closed work (after the type filter), most first; the person filter's options. */
export function closers(items: InsightItem[], types: string[] = []): { name: string; count: number }[] {
  const counts = new Map<string, number>()
  items.filter(i => isClosed(i) && (!types.length || types.includes(i.type))).forEach(i => counts.set(i.assigned_to, (counts.get(i.assigned_to) ?? 0) + 1))
  return [...counts].map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))
}

/** Closed work items per sprint, oldest sprint first (by when its work closed), counted for the chosen people and types. */
export function closedBySprint(items: InsightItem[], filters: ClosedFilters): SprintBar[] {
  const bars = new Map<string, SprintBar>()
  for (const item of items) {
    if (!isClosed(item)) continue
    if (filters.types.length && !filters.types.includes(item.type)) continue
    if (filters.persons.length && !filters.persons.includes(item.assigned_to)) continue
    const bar = bars.get(item.sprint) ?? { sprint: item.sprint, label: '', total: 0, byPerson: {}, lastClosed: '' }
    bar.total += 1
    bar.byPerson[item.assigned_to] = (bar.byPerson[item.assigned_to] ?? 0) + 1
    if ((item.closed ?? '') > bar.lastClosed) bar.lastClosed = item.closed ?? ''
    bars.set(item.sprint, bar)
  }
  const ordered = [...bars.values()].sort((a, b) => a.lastClosed.localeCompare(b.lastClosed))
  const labels = sprintLabels(ordered.map(b => b.sprint))
  return ordered.map(b => ({ ...b, label: labels[b.sprint] }))
}

/** One stacked series per person; with many people the biggest are kept and the rest become "Others". */
export function personSeries(bars: SprintBar[], limit = MAX_SERIES): { name: string; data: number[] }[] {
  const totals = new Map<string, number>()
  bars.forEach(b => Object.entries(b.byPerson).forEach(([p, n]) => totals.set(p, (totals.get(p) ?? 0) + n)))
  const ranked = [...totals].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([p]) => p)
  const shown = ranked.length > limit ? ranked.slice(0, limit - 1) : ranked
  const series = shown.map(p => ({ name: p, data: bars.map(b => b.byPerson[p] ?? 0) }))
  if (ranked.length > shown.length) {
    const rest = ranked.slice(shown.length)
    series.push({ name: 'Others', data: bars.map(b => rest.reduce((sum, p) => sum + (b.byPerson[p] ?? 0), 0)) })
  }
  return series
}

// ---------------------------------------------------------------- section 2: work items by area

export type AreaRow = { area: string; backlog: number; active: number; closed: number; total: number }

/** Backlog (not started), active (started or resolved) and closed items per area. Removed items are never in the data. */
export function areaSummary(items: InsightItem[], types: string[] = []): AreaRow[] {
  const rows = new Map<string, AreaRow>()
  for (const item of items) {
    if (types.length && !types.includes(item.type)) continue
    const row = rows.get(item.area) ?? { area: item.area, backlog: 0, active: 0, closed: 0, total: 0 }
    if (item.state_category === 'proposed') row.backlog += 1
    else if (item.state_category === 'completed') row.closed += 1
    else row.active += 1
    row.total += 1
    rows.set(item.area, row)
  }
  return [...rows.values()].sort(byTotalThenCatchAll)
}

// ---------------------------------------------------------------- section 3: bugs by area

export type BugRow = { area: string; total: number; open: number; closed: number }
export type BugAnalysis = {
  total: number
  /** Open bugs raised before the window; they are not in the charts. */
  olderOpen: number
  rows: BugRow[]
  months: string[]
  series: { area: string; counts: number[] }[]
}

/** Bugs raised (created) inside the window, by area and by month. */
export function bugsByArea(items: InsightItem[], bugTypes: string[], months: string[], maxSeries = 8): BugAnalysis {
  const bugs = items.filter(i => bugTypes.includes(i.type))
  const raised = bugs.filter(i => months.includes(monthKey(i.created)))
  const olderOpen = bugs.filter(i => i.state_category !== 'completed' && !months.includes(monthKey(i.created))).length

  const rows = new Map<string, BugRow>()
  for (const bug of raised) {
    const row = rows.get(bug.area) ?? { area: bug.area, total: 0, open: 0, closed: 0 }
    row.total += 1
    if (bug.state_category === 'completed') row.closed += 1
    else row.open += 1
    rows.set(bug.area, row)
  }
  const sortedRows = [...rows.values()].sort(byTotalThenCatchAll)

  const real = sortedRows.filter(r => !isCatchAll(r.area))
  const shown = new Set(real.slice(0, maxSeries).map(r => r.area))
  const bucket = (area: string) => (shown.has(area) ? area : isCatchAll(area) ? area : OTHER_AREAS_LABEL)
  const counts = new Map<string, number[]>()
  for (const bug of raised) {
    const key = bucket(bug.area)
    const row = counts.get(key) ?? months.map(() => 0)
    row[months.indexOf(monthKey(bug.created))] += 1
    counts.set(key, row)
  }
  // The biggest areas first, then the rolled-up small ones, then the catch-all areas.
  const order = [...shown, OTHER_AREAS_LABEL, ...CATCH_ALL_AREAS].filter(a => counts.has(a))
  return { total: raised.length, olderOpen, rows: sortedRows, months, series: order.map(area => ({ area, counts: counts.get(area)! })) }
}

// ---------------------------------------------------------------- section 4: alert scope

export type AlertAnalysis = {
  items: InsightItem[]
  open: number
  closed: number
  /** 'Earlier' (before the window) followed by the window's months. */
  buckets: string[]
  openByBucket: number[]
  closedByBucket: number[]
  /** False when no item was ever checked: no AI, or the inventory was uploaded after the last refresh. */
  checked: boolean
}

/** Work items created to build new alerts, by the month they were raised. */
export function alertScope(items: InsightItem[], months: string[]): AlertAnalysis {
  const buckets = [EARLIER_LABEL, ...months]
  const alertItems = items.filter(i => i.alert_work === true)
  const open = buckets.map(() => 0)
  const closed = buckets.map(() => 0)
  for (const item of alertItems) {
    const at = months.indexOf(monthKey(item.created)) + 1 // 0 (Earlier) when before the window
    if (item.state_category === 'completed') closed[at] += 1
    else open[at] += 1
  }
  return {
    items: alertItems,
    open: open.reduce((a, b) => a + b, 0),
    closed: closed.reduce((a, b) => a + b, 0),
    buckets,
    openByBucket: open,
    closedByBucket: closed,
    checked: items.some(i => i.alert_work !== null),
  }
}

// ---------------------------------------------------------------- misc

/** The most items a table lists at once. */
export const MAX_LISTED = 300

export function workItemUrl(organization: string, project: string, id: number): string {
  return `https://dev.azure.com/${encodeURIComponent(organization)}/${encodeURIComponent(project)}/_workitems/edit/${id}`
}

export const shortDate = (iso: string | null): string => (iso ? iso.slice(0, 10) : '')
