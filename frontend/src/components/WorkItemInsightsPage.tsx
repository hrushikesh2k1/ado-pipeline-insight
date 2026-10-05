import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactECharts from 'echarts-for-react'
import { ChartColumn, ChevronDown, ExternalLink, Info, RefreshCw, Search, Sparkles, Trash2, TriangleAlert, Upload, X } from 'lucide-react'
import './WorkItemInsightsPage.css'
import { api } from '../services/api'
import type { AdoTeam, InsightItem, InsightScope, WorkItemInsights } from '../types/api'
import {
  MAX_LISTED,
  OTHER_AREAS_LABEL,
  alertScope,
  areaSummary,
  bugsByArea,
  closedBySprint,
  closers,
  isClosed,
  monthKey,
  monthLabel,
  personSeries,
  shortDate,
  windowMonths,
  workItemUrl,
  EARLIER_LABEL,
} from '../utils/workItemInsights'
import {
  alertCategoriesOption,
  alertsByMonthOption,
  areaOptions,
  barChartHeight,
  bugsByAreaOption,
  bugsByMonthOption,
  closedBySprintOption,
} from '../utils/workItemCharts'

interface WorkItemInsightsPageProps {
  organization?: string
  project?: string
  pat?: string
  projects?: Array<{ id: string; name: string }>
  onOrganizationChange?: (org: string) => void
  onProjectChange?: (proj: string) => void
  onPatChange?: (pat: string) => void
  theme?: 'dark' | 'light'
}

const MAX_UPLOAD_BYTES = 5_000_000
const WINDOW_MONTHS = 6
const ACCEPTED_FILES = '.xlsx,.csv,.tsv,.md,.markdown,.txt'

const savedScopeKey = (org: string, project: string) => `ado_insights_scope:${org.toLowerCase()}:${project.toLowerCase()}`

function readSavedScope(org: string, project: string): { team: string; tag: string } {
  try {
    const raw = localStorage.getItem(savedScopeKey(org, project))
    const parsed = raw ? JSON.parse(raw) : null
    return { team: typeof parsed?.team === 'string' ? parsed.team : '', tag: typeof parsed?.tag === 'string' ? parsed.tag : '' }
  } catch {
    return { team: '', tag: '' }
  }
}

function saveScope(org: string, project: string, team: string, tag: string) {
  try {
    localStorage.setItem(savedScopeKey(org, project), JSON.stringify({ team, tag }))
  } catch {
    /* private window or blocked storage: the page works without it */
  }
}

const readBase64 = (file: File) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '')
    reader.onerror = () => reject(new Error('The file could not be read.'))
    reader.readAsDataURL(file)
  })

const errorText = (e: unknown) => (e instanceof Error ? e.message.replace(/^\d+:\s*/, '') : 'Something went wrong.')

// ---------------------------------------------------------------- small parts

const FilterMenu: React.FC<{
  label: string
  options: { name: string; count?: number }[]
  selected: string[]
  onChange: (value: string[]) => void
  testId: string
}> = ({ label, options, selected, onChange, testId }) => {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  const shown = options.filter(o => o.name.toLowerCase().includes(query.trim().toLowerCase()))
  const summary = selected.length === 0 ? 'All' : selected.length === 1 ? selected[0] : `${selected.length} selected`
  const toggle = (name: string) => onChange(selected.includes(name) ? selected.filter(s => s !== name) : [...selected, name])

  return (
    <div className="wiiFilter" ref={ref}>
      <button type="button" className={`wiiFilterBtn ${selected.length ? 'active' : ''}`} onClick={() => setOpen(o => !o)} data-testid={testId} aria-expanded={open}>
        <span>{label}: <b>{summary}</b></span>
        <ChevronDown size={13} />
      </button>
      {open && (
        <div className="wiiFilterMenu" role="listbox" aria-label={label}>
          {options.length > 8 && (
            <div className="wiiFilterSearch">
              <Search size={12} />
              <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search" autoFocus />
            </div>
          )}
          <div className="wiiFilterList">
            {shown.length === 0 && <div className="wiiFilterEmpty">Nothing matches</div>}
            {shown.map(option => (
              <label key={option.name} className="wiiFilterOption">
                <input type="checkbox" checked={selected.includes(option.name)} onChange={() => toggle(option.name)} />
                <span className="wiiFilterName">{option.name}</span>
                {option.count !== undefined && <span className="wiiFilterCount">{option.count}</span>}
              </label>
            ))}
          </div>
          <div className="wiiFilterFoot">
            <button type="button" onClick={() => onChange([])} disabled={selected.length === 0}>Show all</button>
            <button type="button" onClick={() => setOpen(false)}>Done</button>
          </div>
        </div>
      )}
    </div>
  )
}

const Section: React.FC<{ id: string; title: string; hint: string; controls?: React.ReactNode; children: React.ReactNode }> = ({ id, title, hint, controls, children }) => (
  <section className="wiiCard" data-testid={id}>
    <div className="wiiCardHead">
      <div>
        <h3>{title}</h3>
        <p>{hint}</p>
      </div>
      {controls && <div className="wiiControls">{controls}</div>}
    </div>
    {children}
  </section>
)

const Kpi: React.FC<{ label: string; value: string | number; sub?: string; testId: string }> = ({ label, value, sub, testId }) => (
  <div className="wiiKpi" data-testid={testId}>
    <span className="wiiKpiLabel">{label}</span>
    <b className="wiiKpiValue">{value}</b>
    {sub && <span className="wiiKpiSub">{sub}</span>}
  </div>
)

const ItemsDrawer: React.FC<{ title: string; items: InsightItem[]; organization: string; project: string; onClose: () => void }> = ({ title, items, organization, project, onClose }) => {
  const [query, setQuery] = useState('')
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const needle = query.trim().toLowerCase()
  const matching = items.filter(i => !needle || i.title.toLowerCase().includes(needle) || String(i.id).includes(needle) || i.assigned_to.toLowerCase().includes(needle))
  const listed = matching.slice(0, MAX_LISTED)
  return (
    <div className="wiiDrawerShade" onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <aside className="wiiDrawer" role="dialog" aria-label={title} data-testid="wii-drawer">
        <div className="wiiDrawerHead">
          <div>
            <h3>{title}</h3>
            <p>{items.length} work item{items.length === 1 ? '' : 's'}{matching.length !== items.length ? `, ${matching.length} match` : ''}</p>
          </div>
          <button type="button" className="wiiIconBtn" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </div>
        <div className="wiiFilterSearch wiiDrawerSearch">
          <Search size={12} />
          <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search by title, id or person" />
        </div>
        <div className="wiiTableWrap">
          <table className="wiiTable">
            <thead>
              <tr><th>ID</th><th>Title</th><th>Type</th><th>State</th><th>Assigned to</th><th>Area</th><th>Sprint</th><th>Created</th><th>Closed</th></tr>
            </thead>
            <tbody>
              {listed.map(item => (
                <tr key={item.id}>
                  <td><a href={workItemUrl(organization, project, item.id)} target="_blank" rel="noreferrer">{item.id}<ExternalLink size={10} /></a></td>
                  <td className="wiiTitleCell">{item.title}</td>
                  <td>{item.type}</td>
                  <td>{item.state}</td>
                  <td>{item.assigned_to}</td>
                  <td>{item.area}</td>
                  <td>{item.sprint}</td>
                  <td>{shortDate(item.created)}</td>
                  <td>{shortDate(item.closed)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {matching.length > listed.length && <p className="wiiMore">Showing the first {MAX_LISTED} of {matching.length}. Search to narrow the list.</p>}
        </div>
      </aside>
    </div>
  )
}

// ---------------------------------------------------------------- the page

export const WorkItemInsightsPage: React.FC<WorkItemInsightsPageProps> = ({
  organization = '',
  project = '',
  pat = '',
  projects = [],
  onOrganizationChange,
  onProjectChange,
  onPatChange,
  theme = 'dark',
}) => {
  const org = organization.trim()
  const [team, setTeam] = useState('')
  const [tag, setTag] = useState('')
  const [tagDraft, setTagDraft] = useState('')
  const [teams, setTeams] = useState<AdoTeam[]>([])
  const [data, setData] = useState<WorkItemInsights | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')

  const [closedPersons, setClosedPersons] = useState<string[]>([])
  const [closedTypes, setClosedTypes] = useState<string[]>([])
  const [areaTypes, setAreaTypes] = useState<string[]>([])
  const [bugTypeChoice, setBugTypeChoice] = useState<string[] | null>(null)
  const [bugView, setBugView] = useState<'area' | 'month'>('area')
  const [drawer, setDrawer] = useState<{ title: string; items: InsightItem[] } | null>(null)

  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [lastUpload, setLastUpload] = useState<{ name: string; base64: string } | null>(null)
  const [nameColumn, setNameColumn] = useState('')
  const [categoryColumn, setCategoryColumn] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const latestLoad = useRef(0)

  const scope: InsightScope = useMemo(() => ({ organization: org, project, team, tag }), [org, project, team, tag])
  const ready = !!org && !!project

  // A saved team/tag per organization and project, so a monitoring team opens straight on its own tag.
  useEffect(() => {
    if (!ready) return
    const saved = readSavedScope(org, project)
    setTeam(saved.team)
    setTag(saved.tag)
    setTagDraft(saved.tag)
    setBugTypeChoice(null)
    setClosedPersons([])
    setClosedTypes([])
    setAreaTypes([])
  }, [org, project, ready])

  useEffect(() => {
    if (!ready) return
    let current = true
    api.teams(org, project, pat || undefined).then(list => current && setTeams(list)).catch(() => current && setTeams([]))
    return () => { current = false }
  }, [org, project, pat, ready])

  const load = useCallback(async () => {
    if (!ready) return
    const ticket = ++latestLoad.current
    setLoading(true)
    try {
      const snapshot = await api.workItemInsights(scope)
      if (ticket === latestLoad.current) {
        setData(snapshot)
        setError('')
      }
    } catch (e) {
      if (ticket === latestLoad.current) setError(errorText(e))
    } finally {
      if (ticket === latestLoad.current) setLoading(false)
    }
  }, [scope, ready])

  useEffect(() => { void load() }, [load])

  // While a refresh runs, follow its progress and reload the page data when it ends.
  const running = data?.job.status === 'running'
  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(async () => {
      try {
        const job = await api.workItemInsightsStatus(scope)
        setData(d => (d ? { ...d, job } : d))
        if (job.status !== 'running') void load()
      } catch {
        /* a missed poll is fine; the next one will catch up */
      }
    }, 1500)
    return () => window.clearInterval(timer)
  }, [running, scope, load])

  const startRefresh = async (regroup = false) => {
    setError('')
    setInfo('')
    try {
      await api.refreshWorkItemInsights(scope, { regroup, months: WINDOW_MONTHS }, pat || undefined)
      // Reload now, whatever state the job is in: a refresh with nothing new can finish before anything starts watching it.
      await load()
    } catch (e) {
      setError(errorText(e))
    }
  }

  const applyTag = () => {
    const next = tagDraft.trim()
    if (next !== tag) {
      setTag(next)
      saveScope(org, project, team, next)
    }
  }

  const changeTeam = (value: string) => {
    setTeam(value)
    saveScope(org, project, value, tag)
  }

  // ---- what the four sections show
  const items = data?.items ?? []
  const months = useMemo(() => windowMonths(new Date(), data?.scope.months ?? WINDOW_MONTHS), [data?.scope.months])
  const bugTypes = bugTypeChoice ?? data?.bug_types ?? []

  const sprintBars = useMemo(() => closedBySprint(items, { persons: closedPersons, types: closedTypes }), [items, closedPersons, closedTypes])
  const shownPersons = useMemo(() => personSeries(sprintBars).map(s => s.name), [sprintBars])
  const areaRows = useMemo(() => areaSummary(items, areaTypes), [items, areaTypes])
  const bugs = useMemo(() => bugsByArea(items, bugTypes, months), [items, bugTypes, months])
  const alerts = useMemo(() => alertScope(items, months), [items, months])

  const closedCount = items.filter(isClosed).length
  const openCount = items.length - closedCount
  const aiGrouped = data?.area_source === 'ai'

  const openList = (title: string, predicate: (item: InsightItem) => boolean) => {
    const list = items.filter(predicate).sort((a, b) => (b.created ?? '').localeCompare(a.created ?? ''))
    setDrawer({ title, items: list })
  }

  const onSprintClick = (p: { name?: string; seriesName?: string }) => {
    const bar = sprintBars.find(b => b.label === p.name)
    if (!bar) return
    const person = p.seriesName
    const matches = (i: InsightItem) =>
      isClosed(i) && i.sprint === bar.sprint && (!closedTypes.length || closedTypes.includes(i.type)) &&
      (!closedPersons.length || closedPersons.includes(i.assigned_to)) &&
      (!person ? true : person === 'Others' ? !shownPersons.includes(i.assigned_to) : i.assigned_to === person)
    openList(`Closed in ${bar.label}${person ? ` · ${person}` : ''}`, matches)
  }

  const onAreaClick = (p: { name?: string; seriesName?: string }) => {
    const part = p.seriesName
    const group = (i: InsightItem) => (i.state_category === 'proposed' ? 'Backlog' : i.state_category === 'completed' ? 'Closed' : 'Active')
    openList(`${p.name}${part && part !== 'Total' ? ` · ${part}` : ''}`, i =>
      i.area === p.name && (!areaTypes.length || areaTypes.includes(i.type)) && (!part || part === 'Total' || group(i) === part))
  }

  const onBugAreaClick = (p: { name?: string; seriesName?: string }) => {
    openList(`Bugs in ${p.name}${p.seriesName && p.seriesName !== 'Total' ? ` · ${p.seriesName}` : ''}`, i =>
      bugTypes.includes(i.type) && i.area === p.name && months.includes(monthKey(i.created)) &&
      (!p.seriesName || p.seriesName === 'Total' || (p.seriesName === 'Closed') === (i.state_category === 'completed')))
  }

  const onBugMonthClick = (p: { seriesName?: string; dataIndex?: number }) => {
    const month = months[p.dataIndex ?? -1]
    const shown = bugs.series.map(s => s.area)
    openList(`${p.seriesName} · bugs raised in ${monthLabel(month ?? '')}`, i =>
      bugTypes.includes(i.type) && monthKey(i.created) === month &&
      (p.seriesName === OTHER_AREAS_LABEL ? !shown.includes(i.area) : i.area === p.seriesName))
  }

  const onAlertClick = (p: { seriesName?: string; dataIndex?: number }) => {
    const bucket = alerts.buckets[p.dataIndex ?? -1]
    openList(`${p.seriesName} work items that build alerts · ${bucket === EARLIER_LABEL ? 'raised before ' + monthLabel(months[0]) : monthLabel(bucket ?? '')}`, i =>
      i.alert_work === true && (i.state_category === 'completed') === (p.seriesName === 'Closed') &&
      (bucket === EARLIER_LABEL ? !months.includes(monthKey(i.created)) : monthKey(i.created) === bucket))
  }

  // ---- alert inventory
  const sendInventory = async (file: { name: string; base64: string }, columns?: { name: string; category: string }) => {
    setUploading(true)
    setUploadError('')
    try {
      const summary = await api.uploadAlertInventory({
        ...scope,
        filename: file.name,
        content_base64: file.base64,
        name_column: columns?.name || undefined,
        category_column: columns ? (columns.category === '' ? '' : columns.category) : undefined,
      })
      setData(d => (d ? { ...d, inventory: summary } : d))
      setNameColumn(summary.name_column ?? '')
      setCategoryColumn(summary.category_column ?? '')
      if (data?.has_data) {
        setInfo('Alert inventory saved. Looking for the work items that build alerts…')
        void startRefresh(false)
      } else {
        setInfo('Alert inventory saved. Refresh the work items to find the ones that build alerts.')
      }
    } catch (e) {
      setUploadError(errorText(e))
    } finally {
      setUploading(false)
    }
  }

  const onFileChosen = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    if (file.size > MAX_UPLOAD_BYTES) {
      setUploadError('The file is larger than 5 MB.')
      return
    }
    try {
      const upload = { name: file.name, base64: await readBase64(file) }
      setLastUpload(upload)
      await sendInventory(upload)
    } catch (e) {
      setUploadError(errorText(e))
    }
  }

  const removeInventory = async () => {
    setUploadError('')
    try {
      await api.deleteAlertInventory(scope)
      setData(d => (d ? { ...d, inventory: null } : d))
      setLastUpload(null)
      setInfo('')
    } catch (e) {
      setUploadError(errorText(e))
    }
  }

  const job = data?.job
  const percent = job && job.total > 0 ? Math.min(100, Math.round((job.done / job.total) * 100)) : null
  const inventory = data?.inventory ?? null
  const typeOptions = (data?.types ?? []).map(t => ({ name: t.name, count: t.count }))
  const chartTheme = theme === 'light' ? 'light' : 'dark'

  return (
    <div className="wiiPage" data-testid="work-item-insights-page">
      <div className="wiiBanner">
        <div className="wiiBannerIcon"><ChartColumn size={22} /></div>
        <div>
          <h2>Work Item Insights</h2>
          <p>What your work items are about, who closes them, where bugs come from and how many alerts exist. Pick a team or a tag to look at one team's work.</p>
        </div>
      </div>

      <div className="prToolbar wiiToolbar">
        <div className="prToolbarLeft">
          <div className="prToolbarItem">
            <span className="prToolbarLabel">Org:</span>
            <input type="text" className="prOrgInput" placeholder="Organization" value={organization} onChange={e => onOrganizationChange?.(e.target.value)} />
          </div>
          <div className="prToolbarItem">
            <span className="prToolbarLabel">PAT:</span>
            <input type="password" className="prPatInput" placeholder={pat ? '••••••••••••••••' : 'PAT Token'} value={pat} onChange={e => onPatChange?.(e.target.value)} autoComplete="off" />
          </div>
          <div className="prToolbarItem">
            <span className="prToolbarLabel">Project:</span>
            <div className="prCustomSelectWrapper">
              <select className="prCustomSelect" value={project} onChange={e => onProjectChange?.(e.target.value)} data-testid="wii-project">
                <option value="">Select Project</option>
                {projects.map(p => <option key={p.id} value={p.name}>{p.name}</option>)}
              </select>
              <ChevronDown size={14} className="prSelectArrow" />
            </div>
          </div>
          <div className="prToolbarItem">
            <span className="prToolbarLabel">Team:</span>
            <div className="prCustomSelectWrapper">
              <select className="prCustomSelect" value={team} onChange={e => changeTeam(e.target.value)} data-testid="wii-team">
                <option value="">All teams</option>
                {team && !teams.some(t => t.name === team) && <option value={team}>{team}</option>}
                {teams.map(t => <option key={t.id} value={t.name}>{t.name}</option>)}
              </select>
              <ChevronDown size={14} className="prSelectArrow" />
            </div>
          </div>
          <div className="prToolbarItem">
            <span className="prToolbarLabel">Tag:</span>
            <input
              type="text"
              className="prOrgInput wiiTagInput"
              placeholder="any (for example monitoring)"
              value={tagDraft}
              onChange={e => setTagDraft(e.target.value)}
              onBlur={applyTag}
              onKeyDown={e => e.key === 'Enter' && applyTag()}
              data-testid="wii-tag"
            />
          </div>
        </div>
        <div className="prToolbarRight wiiActions">
          <button type="button" className="wiiGhostBtn" onClick={() => { if (window.confirm('Regroup asks the AI to propose new areas and sorts every work item again, so the counts per area can change. Continue?')) void startRefresh(true) }} disabled={!ready || running || !data?.has_data} data-testid="wii-regroup" title="Ask the AI for a new list of areas">
            <Sparkles size={13} /> Regroup areas
          </button>
          <button type="button" className="prRefreshBtn" onClick={() => void startRefresh(false)} disabled={!ready || running} data-testid="wii-refresh">
            <RefreshCw size={14} className={running ? 'spin' : ''} /> {running ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </div>

      {!ready && <div className="wiiNotice" data-testid="wii-need-project"><Info size={14} /> Enter an organization and select a project to begin.</div>}
      {error && <div className="wiiNotice error" data-testid="wii-error"><TriangleAlert size={14} /> {error}</div>}
      {job?.status === 'error' && job.error && <div className="wiiNotice error" data-testid="wii-job-error"><TriangleAlert size={14} /> {job.error}</div>}
      {info && <div className="wiiNotice info"><Info size={14} /> {info}</div>}
      {data?.notes.map(note => <div key={note} className="wiiNotice warn" data-testid="wii-note"><TriangleAlert size={14} /> {note}</div>)}

      {running && job && (
        <div className="wiiProgress" data-testid="wii-progress">
          <div className="wiiProgressText"><RefreshCw size={13} className="spin" /> {job.message}</div>
          <div className="wiiProgressBar"><span style={{ width: percent === null ? '100%' : `${percent}%` }} className={percent === null ? 'indeterminate' : ''} /></div>
        </div>
      )}

      {ready && data && !data.has_data && !running && (
        <div className="wiiEmpty" data-testid="wii-empty">
          <ChartColumn size={26} />
          <h3>Nothing to show yet for this scope</h3>
          <p>
            Click <b>Refresh</b> to read the {tag ? <>work items tagged <b>{tag}</b></> : team ? <>work items of <b>{team}</b></> : 'work items'} from Azure DevOps: everything still open, plus what closed in the last {WINDOW_MONTHS} months.
            You need a personal access token with the <b>Work Items: Read</b> scope{data.ai_configured ? '' : ' (and Azure OpenAI is not configured, so areas will follow the Azure DevOps Area Path)'}.
          </p>
        </div>
      )}

      {data?.has_data && (
        <>
          <div className="wiiKpis">
            <Kpi testId="wii-kpi-total" label="Work items" value={items.length} sub={`${tag ? `tag ${tag}` : team || 'whole project'}`} />
            <Kpi testId="wii-kpi-open" label="Open backlog" value={openCount} sub="not closed" />
            <Kpi testId="wii-kpi-closed" label="Closed" value={closedCount} sub={`last ${data.scope.months} months`} />
            <Kpi testId="wii-kpi-areas" label="Areas" value={data.areas.length || new Set(items.map(i => i.area)).size} sub={aiGrouped ? 'grouped by AI' : 'from Area Path'} />
            <Kpi testId="wii-kpi-refreshed" label="Last refreshed" value={data.refreshed_at ? new Date(data.refreshed_at).toLocaleDateString() : '—'} sub={data.refreshed_at ? new Date(data.refreshed_at).toLocaleTimeString() : ''} />
          </div>

          <Section
            id="wii-section-closed"
            title="1 · Work items closed per sprint"
            hint="Each bar is a sprint; each colour is a person. Click a bar to see the work items."
            controls={
              <>
                <FilterMenu label="People" options={closers(items, closedTypes)} selected={closedPersons} onChange={setClosedPersons} testId="wii-filter-persons" />
                <FilterMenu label="Types" options={typeOptions} selected={closedTypes} onChange={setClosedTypes} testId="wii-filter-closed-types" />
              </>
            }
          >
            {sprintBars.length === 0 ? <p className="wiiNone">No closed work items for this selection.</p> : (
              <ReactECharts option={closedBySprintOption(sprintBars, chartTheme)} style={{ height: 340 }} notMerge onEvents={{ click: onSprintClick }} />
            )}
          </Section>

          <Section
            id="wii-section-areas"
            title="2 · Work items by area"
            hint={aiGrouped
              ? 'The AI read each work item\'s title and description and put it in one area. Backlog, active and closed work are all counted. Click a bar to see the items.'
              : 'Grouped by Azure DevOps Area Path (the AI is not available). Backlog, active and closed work are all counted.'}
            controls={<FilterMenu label="Types" options={typeOptions} selected={areaTypes} onChange={setAreaTypes} testId="wii-filter-area-types" />}
          >
            {areaRows.length === 0 ? <p className="wiiNone">No work items.</p> : (
              <ReactECharts option={areaOptions(areaRows, chartTheme)} style={{ height: barChartHeight(areaRows.length) }} notMerge onEvents={{ click: onAreaClick }} />
            )}
            {aiGrouped && data.areas.length > 0 && (
              <details className="wiiAreaList">
                <summary>What each area means</summary>
                <ul>{data.areas.map(a => <li key={a.name}><b>{a.name}</b>{a.description ? ` — ${a.description}` : ''}</li>)}</ul>
              </details>
            )}
          </Section>

          <Section
            id="wii-section-bugs"
            title="3 · Bugs raised by area"
            hint={`Bugs created in the last ${data.scope.months} months. ${bugs.olderOpen ? `${bugs.olderOpen} open bug${bugs.olderOpen === 1 ? ' was' : 's were'} raised earlier and ${bugs.olderOpen === 1 ? 'is' : 'are'} not shown. ` : ''}Click a bar to see the bugs.`}
            controls={
              <>
                <FilterMenu label="Bug types" options={typeOptions} selected={bugTypes} onChange={v => setBugTypeChoice(v)} testId="wii-filter-bug-types" />
                <div className="wiiToggle" role="group" aria-label="Bug chart">
                  <button type="button" className={bugView === 'area' ? 'active' : ''} onClick={() => setBugView('area')} data-testid="wii-bugs-by-area">By area</button>
                  <button type="button" className={bugView === 'month' ? 'active' : ''} onClick={() => setBugView('month')} data-testid="wii-bugs-by-month">Over time</button>
                </div>
              </>
            }
          >
            {bugTypes.length === 0 ? <p className="wiiNone">No work item type is chosen as a bug. Use “Bug types” to choose one.</p>
              : bugs.total === 0 ? <p className="wiiNone">No bugs were raised in this period.</p>
              : bugView === 'area' ? (
                <ReactECharts option={bugsByAreaOption(bugs.rows, chartTheme)} style={{ height: barChartHeight(bugs.rows.length) }} notMerge onEvents={{ click: onBugAreaClick }} />
              ) : (
                <ReactECharts option={bugsByMonthOption(bugs, chartTheme)} style={{ height: 340 }} notMerge onEvents={{ click: onBugMonthClick }} />
              )}
          </Section>

          <Section
            id="wii-section-alerts"
            title="4 · Alert scope"
            hint="The alerts in production, from your inventory, next to the work items raised to build new alerts."
            controls={
              <>
                <input ref={fileInput} type="file" accept={ACCEPTED_FILES} hidden onChange={onFileChosen} data-testid="wii-upload-input" />
                <button type="button" className="wiiGhostBtn" onClick={() => fileInput.current?.click()} disabled={uploading} data-testid="wii-upload">
                  <Upload size={13} /> {inventory ? 'Replace inventory' : 'Upload alert inventory'}
                </button>
                {inventory && <button type="button" className="wiiGhostBtn danger" onClick={() => void removeInventory()} data-testid="wii-remove-inventory"><Trash2 size={13} /> Remove</button>}
              </>
            }
          >
            {uploadError && <div className="wiiNotice error" data-testid="wii-upload-error"><TriangleAlert size={14} /> {uploadError}</div>}
            {!inventory ? (
              <div className="wiiUploadBox" data-testid="wii-upload-box">
                <Upload size={20} />
                <p><b>Upload your alert inventory</b> (.xlsx, .csv, .tsv, .md or .txt, up to 5 MB) to see how many alerts exist. The file needs a header row with a column for the alert name.</p>
                <button type="button" className="prRefreshBtn" onClick={() => fileInput.current?.click()} disabled={uploading}>{uploading ? 'Reading…' : 'Choose a file'}</button>
              </div>
            ) : (
              <>
                <div className="wiiKpis wiiKpisSmall">
                  <Kpi testId="wii-alert-count" label="Alerts in production" value={inventory.count} sub={inventory.filename ?? ''} />
                  <Kpi testId="wii-alert-items" label="Work items to build alerts" value={alerts.checked ? alerts.items.length : '—'} sub={alerts.checked ? `${alerts.closed} closed · ${alerts.open} open` : 'not checked yet'} />
                </div>
                {!alerts.checked && (
                  <div className="wiiNotice info" data-testid="wii-alerts-unchecked">
                    <Info size={14} /> {data.ai_configured ? 'Click Refresh to find the work items that build alerts.' : 'Finding the work items that build alerts needs Azure OpenAI, which is not configured on this server.'}
                  </div>
                )}
                <div className="wiiTwoCol">
                  <div>
                    <h4>Work items raised to build alerts</h4>
                    {alerts.checked ? <ReactECharts option={alertsByMonthOption(alerts, chartTheme)} style={{ height: 280 }} notMerge onEvents={{ click: onAlertClick }} /> : <p className="wiiNone">Not checked yet.</p>}
                  </div>
                  <div>
                    <h4>{inventory.categories.length ? `Alerts by ${inventory.category_column ?? 'category'}` : 'Alerts'}</h4>
                    {inventory.categories.length ? (
                      <ReactECharts option={alertCategoriesOption(inventory.categories.slice(0, 20), chartTheme)} style={{ height: barChartHeight(Math.min(20, inventory.categories.length)) }} notMerge />
                    ) : (
                      <p className="wiiNone">The inventory has no grouping column. Example alerts: {inventory.sample.join(', ')}.</p>
                    )}
                  </div>
                </div>
                <details className="wiiAreaList" data-testid="wii-columns">
                  <summary>File details and columns</summary>
                  <p>
                    {inventory.count} alert{inventory.count === 1 ? '' : 's'} read from <b>{inventory.filename}</b>{inventory.sheet ? ` (sheet ${inventory.sheet})` : ''}
                    {inventory.duplicates ? `; ${inventory.duplicates} duplicate name${inventory.duplicates === 1 ? '' : 's'} ignored` : ''}.
                  </p>
                  {lastUpload && inventory.columns.length > 1 && (
                    <div className="wiiColumnPick">
                      <label>Alert name column
                        <select value={nameColumn} onChange={e => setNameColumn(e.target.value)}>
                          {inventory.columns.map(c => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </label>
                      <label>Group alerts by
                        <select value={categoryColumn} onChange={e => setCategoryColumn(e.target.value)}>
                          <option value="">No grouping</option>
                          {inventory.columns.filter(c => c !== nameColumn).map(c => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </label>
                      <button type="button" className="wiiGhostBtn" disabled={uploading} onClick={() => void sendInventory(lastUpload, { name: nameColumn, category: categoryColumn })}>Apply</button>
                    </div>
                  )}
                  {!lastUpload && inventory.columns.length > 1 && <p className="wiiMuted">To change the columns, upload the file again.</p>}
                </details>
              </>
            )}
          </Section>
        </>
      )}

      {drawer && <ItemsDrawer title={drawer.title} items={drawer.items} organization={org} project={project} onClose={() => setDrawer(null)} />}
      {loading && !data && <div className="wiiNotice info"><RefreshCw size={14} className="spin" /> Loading…</div>}
    </div>
  )
}
