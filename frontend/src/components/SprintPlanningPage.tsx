import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Ban, Bot, CalendarCheck, Check, ChevronDown, ChevronUp, Clock, Copy, ExternalLink, MessageSquare,
  Info, Plus, Send, ShieldAlert, Sparkles, Target, TriangleAlert, Users, X,
} from 'lucide-react'
import './SprintPlanningPage.css'
import { api } from '../services/api'
import type { AdoTeam, PlanSprint, PlanStory, PlannedPerson, SprintPlan, SprintPlanningSetup, SprintCommitResponse, VelocityContext } from '../types/api'
import { capacityForPerson, totalCapacityHours, velocityCapacityInput, withSavedCapacity } from '../utils/sprintCapacity'
import {
  ANY_AREA, DEFAULT_ACTIVE_DAYS, DEFAULT_PER_PERSON, MAX_PER_PERSON, MIN_PER_PERSON,
  addPerson, areaLabel, commentDate, daysInState, flagText, fullness, loadPeople, loadRoster, mergeRosterMembers, peopleForPlan, personKey, plural, planAsMarkdown, planProblems,
  reassignStory, rankGoalBacklog, commitAssignments, removePerson, savePeople, saveRoster, setIncluded, sprintLabel, storyCount,
  type GoalEvidence, type PlanningPerson,
} from '../utils/sprintPlanning'

interface SprintPlanningPageProps {
  organization?: string
  project?: string
  pat?: string
  projects?: Array<{ id: string; name: string }>
  onOrganizationChange?: (org: string) => void
  onProjectChange?: (proj: string) => void
  onPatChange?: (pat: string) => void
  theme?: 'dark' | 'light'
}

const teamKey = (org: string, project: string) => `ado_sprint_planning_team:${org.toLowerCase()}:${project.toLowerCase()}`
const errorText = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong.')
const workItemUrl = (story: PlanStory) => story.url

function readSavedTeam(org: string, project: string): string {
  try { return localStorage.getItem(teamKey(org, project)) ?? '' } catch { return '' }
}

// ---------------------------------------------------------------- stories

const FlagChips: React.FC<{ story: PlanStory }> = ({ story }) => (
  <>
    {story.flags.map(flag => (
      <span key={flag.code} className={`sppChip flag ${flag.code}`} title={flag.reason} data-testid={`spp-flag-${flag.code}`}>
        {flag.code === 'blocked' ? <Ban size={11} /> : <Clock size={11} />} {flagText(flag)}
      </span>
    ))}
  </>
)

type StoryComment = NonNullable<PlanStory['comments']>[number]
type LoadComments = (storyId: number) => Promise<StoryComment[]>

const RecentComments: React.FC<{ story: PlanStory; loadComments: LoadComments }> = ({ story, loadComments }) => {
  const [expanded, setExpanded] = useState(false)
  const [comments, setComments] = useState(story.comments)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const id = React.useId()
  const recent = comments ? [...comments].sort((a, b) => a.date.localeCompare(b.date)).slice(-3) : []

  const toggle = async () => {
    setExpanded(!expanded)
    if (expanded || comments !== null || loading) return
    setLoading(true); setError('')
    try {
      setComments(await loadComments(story.id))
    } catch (e) {
      setError(`The comments could not be read: ${errorText(e)}. Hide and reopen to retry.`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <button type="button" className="sppGhost" onClick={() => void toggle()} aria-expanded={expanded} aria-controls={id}>
        <MessageSquare size={13} /> {expanded ? 'Hide Recent Comments' : 'View Recent Comments'}
        {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
      </button>
      {expanded && (
        <div id={id} className="sppComments" data-testid={`spp-comments-${story.id}`}>
          <h5>Last {recent.length ? plural(recent.length, 'comment') : 'comments'} <span>(oldest first)</span></h5>
          {loading && <p className="sppMuted">Loading recent comments…</p>}
          {error && <p role="alert" className="sppMuted">{error}</p>}
          {!loading && !error && comments?.length === 0 && <p className="sppMuted">No comments on this story.</p>}
          {recent.map((c, i) => (
            <blockquote key={`${c.date}-${i}`} data-testid="spp-comment">
              <div className="sppCommentHead"><b>{c.author}</b><span>{commentDate(c.date)}</span></div>
              <p>{c.text}</p>
            </blockquote>
          ))}
        </div>
      )}
    </div>
  )
}

const StoryRow: React.FC<{
  story: PlanStory
  project: string
  loadComments: LoadComments
  note?: string
  people?: PlannedPerson[]
  currentOwner?: string
  goalMatches?: string[]
  goalEvidence?: GoalEvidence[]
  onReassign?: (storyId: number, targetPersonName: string) => void
}> = ({ story, project, loadComments, note, people, currentOwner, goalMatches, goalEvidence, onReassign }) => (
  <li className={`sppStory${goalMatches?.length ? ' sppGoalMatch' : ''}`} data-testid={`spp-story-${story.id}`}>
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
      <a href={workItemUrl(story)} target="_blank" rel="noreferrer" className="sppStoryTitle">
        <span className="sppId">#{story.id}</span> {story.title}<ExternalLink size={10} />
      </a>
      {people && onReassign && (
        <select
          className="sppReassignSelect"
          value={currentOwner ?? ''}
          onChange={e => onReassign(story.id, e.target.value)}
          aria-label={`Reassign story ${story.id}`}
        >
          <option value="">(Not in plan)</option>
          {people.map(p => (
            <option key={personKey(p)} value={personKey(p)}>{p.name}</option>
          ))}
        </select>
      )}
    </div>
    <div className="sppStoryMeta">
      <span className="sppChip">{story.state}</span>
      <FlagChips story={story} />
      {story.points !== null && <span className="sppChip points">{story.points} pts</span>}
      <span className="sppArea" title={story.area_path}>{areaLabel(story.area_path, project)}</span>
      {note && <span className="sppNote">{note}</span>}
      {!!goalMatches?.length && <span className="sppChip" title={`Matching topics: ${goalMatches.join(', ')}`}><Target size={11} /> Sprint Goal match</span>}
    </div>
    {goalEvidence?.map(item => (
      <p className="sppMuted" key={item.topic} data-testid="spp-goal-evidence">Matched "{item.topic}" in {item.source}: "{item.excerpt}"</p>
    ))}
    <RecentComments story={story} loadComments={loadComments} />
  </li>
)

const FlaggedCard: React.FC<{
  story: PlanStory
  project: string
  loadComments: LoadComments
  onDrop?: (storyId: number) => void
}> = ({ story, project, loadComments, onDrop }) => (
  <article className="sppFlagged" data-testid={`spp-flagged-${story.id}`}>
    <div className="sppFlaggedHead">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}>
        <a href={workItemUrl(story)} target="_blank" rel="noreferrer" className="sppStoryTitle"><span className="sppId">#{story.id}</span> {story.title}<ExternalLink size={10} /></a>
        {onDrop && (
          <button type="button" className="sppGhost" style={{ padding: '2px 8px', fontSize: '11px' }} onClick={() => onDrop(story.id)}>
            Remove from plan
          </button>
        )}
      </div>
      <div className="sppStoryMeta">
        <span className="sppOwner">{story.assigned_to || 'Nobody'}</span>
        <span className="sppChip">{story.state}{daysInState(story) ? ` · ${daysInState(story)}` : ''}</span>
        {story.points !== null && <span className="sppChip points">{story.points} pts</span>}
        <FlagChips story={story} />
        <span className="sppArea" title={story.area_path}>{areaLabel(story.area_path, project)}</span>
      </div>
      <ul className="sppReasons">{story.flags.map(f => <li key={f.code}>{f.reason}</li>)}</ul>
    </div>
    <RecentComments story={story} loadComments={loadComments} />
  </article>
)

const PersonCard: React.FC<{
  person: PlannedPerson
  sprintName: string
  project: string
  loadComments: LoadComments
  mode: 'stories' | 'points'
  allPeople?: PlannedPerson[]
  onReassign?: (storyId: number, targetPersonName: string) => void
}> = ({ person, sprintName, project, loadComments, mode, allPeople, onReassign }) => {
  const key = personKey(person)
  const usePointBudget = (person.velocity_based || mode === 'points') && person.points_capacity != null
  const percent = usePointBudget
    ? Math.min(100, Math.round(((person.velocity_based ? person.points_reserved : person.points_planned) ?? 0) / Math.max(1, person.points_capacity ?? 0) * 100))
    : Math.min(100, Math.round((person.total / Math.max(1, person.capacity)) * 100))

  const isOver = usePointBudget
    ? ((person.velocity_based ? person.points_reserved : person.points_planned) ?? 0) > (person.points_capacity ?? 0)
    : person.over_by > 0

  const hasRoom = person.velocity_based ? (person.points_open ?? 0) > 0 : person.open_places > 0
  const state = isOver ? 'over' : hasRoom ? 'short' : 'full'

  const countDisplay = person.velocity_based && person.forecast_status !== 'ready'
    ? 'Forecast unavailable'
    : usePointBudget
    ? `${person.velocity_based && mode === 'stories' ? `${person.total} stories · ` : ''}${person.velocity_based ? person.points_reserved ?? 0 : person.points_planned ?? 0} of ${person.points_capacity} pts`
    : fullness(person)

  return (
    <section className={`sppPerson ${state}`} data-testid={`spp-card-${key}`}>
      <div className="sppPersonHead">
        <div>
          <h4>{person.name}</h4>
          <span className="sppMuted">
            {person.areas.length ? person.areas.map(a => areaLabel(a, project)).join(', ') : 'No area of choice'}
            {person.pto_days ? ` · ${person.pto_days}d PTO` : ''}
          </span>
        </div>
        <div className="sppFill" title={`${countDisplay} planned`}>
          <b data-testid={`spp-count-${key}`}>{countDisplay}</b>
          <span className="sppMeter"><span style={{ width: `${percent}%` }} /></span>
        </div>
      </div>
      {person.velocity_based && <p className="sppMuted" data-testid={`spp-forecast-${key}`}>
        Previous completed: {person.previous_completed_points ?? 'unavailable'} pts · Previous available: {person.previous_available_days ?? 'unavailable'} days.
        {' '}Capacity: {person.total_capacity_hours == null ? 'unavailable' : `${person.total_capacity_hours}h`}.
        {' '}Original planned size: {person.points_planned ?? 0} pts; remaining reserved: {person.points_reserved ?? 0} pts.
      </p>}
      {person.carried.length > 0 && (
        <>
          <h5>Carried over from the current sprint <span>({person.carried.length})</span></h5>
          <ul>{person.carried.map(s => <StoryRow key={s.id} story={s} project={project} loadComments={loadComments} people={allPeople} currentOwner={personKey(person)} onReassign={onReassign} />)}</ul>
        </>
      )}
      {person.already_planned.length > 0 && (
        <>
          <h5>Already in {sprintName} <span>({person.already_planned.length})</span></h5>
          <ul>{person.already_planned.map(s => <StoryRow key={s.id} story={s} project={project} loadComments={loadComments} people={allPeople} currentOwner={personKey(person)} onReassign={onReassign} />)}</ul>
        </>
      )}
      {person.new.length > 0 && (
        <>
          <h5>New from the backlog <span>({person.new.length})</span></h5>
          <ul>{person.new.map(s => <StoryRow key={s.id} story={s} project={project} loadComments={loadComments} people={allPeople} currentOwner={personKey(person)} onReassign={onReassign} note={s.matched_area ? `area: ${areaLabel(s.matched_area, project)}` : undefined} />)}</ul>
        </>
      )}
      {storyCount(person) === 0 && <p className="sppMuted">No stories planned.</p>}
      {person.warnings.map(w => <p key={w} className="sppWarn" data-testid="spp-person-warning"><TriangleAlert size={12} /> {w}</p>)}
    </section>
  )
}

const Kpi: React.FC<{ label: string; value: string | number; sub?: string; tone?: 'warn' | 'bad'; testId: string }> = ({ label, value, sub, tone, testId }) => (
  <div className={`sppKpi ${tone ?? ''}`} data-testid={testId}><span>{label}</span><b>{value}</b>{sub && <small>{sub}</small>}</div>
)

// ---------------------------------------------------------------- the page

export const LegacySprintPlanningPage: React.FC<SprintPlanningPageProps> = ({
  organization = '', project = '', pat = '', projects = [], onOrganizationChange, onProjectChange, onPatChange,
}) => {
  const org = organization.trim()
  const loadComments = (storyId: number) => api.workItemComments(org, project, storyId, 3, pat || undefined)
  const [teams, setTeams] = useState<AdoTeam[]>([])
  const [team, setTeam] = useState('')
  const [setup, setSetup] = useState<SprintPlanningSetup | null>(null)
  const [loadingSetup, setLoadingSetup] = useState(false)
  const [setupError, setSetupError] = useState('')
  const [fromId, setFromId] = useState('')
  const [toId, setToId] = useState('')
  const [perPerson, setPerPerson] = useState(DEFAULT_PER_PERSON)
  const [activeDays, setActiveDays] = useState(DEFAULT_ACTIVE_DAYS)
  const [sprintGoal, setSprintGoal] = useState('')
  const [capacityMode, setCapacityMode] = useState<'stories' | 'points'>('points')
  const [types, setTypes] = useState<string[]>([])
  const [people, setPeople] = useState<PlanningPerson[]>([])
  const [roster, setRoster] = useState<string[] | null>(null)
  const [rosterEditorOpen, setRosterEditorOpen] = useState(false)
  const [rosterDraft, setRosterDraft] = useState<string[]>([])
  const [rosterSearch, setRosterSearch] = useState('')
  const [rosterError, setRosterError] = useState('')
  const [rosterNotice, setRosterNotice] = useState('')
  const [newPerson, setNewPerson] = useState('')
  const [savedPlan, setPlan] = useState<SprintPlan | null>(null)
  const [planKey, setPlanKey] = useState<string | null>(null)
  const [planning, setPlanning] = useState(false)
  const [committing, setCommitting] = useState(false)
  const [commitModalOpen, setCommitModalOpen] = useState(false)
  const [commitResult, setCommitResult] = useState<SprintCommitResponse | null>(null)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  const [attentionFilter, setAttentionFilter] = useState('all')
  const [velocityContext, setVelocityContext] = useState<VelocityContext | null>(null)
  const [capacityError, setCapacityError] = useState('')
  const [loadingCapacity, setLoadingCapacity] = useState(false)
  const latestCapacity = useRef(0)
  const latestSetup = useRef(0)
  const ready = !!org && !!project && !!team
  const latestPlan = useRef(0)
  const commitInFlight = useRef(false)
  const capacityRefreshPending = useRef(false)
  const setupScope = useRef('')
  const scope = JSON.stringify([org, project, team, pat])
  const rosterPeople = useMemo(() => roster === null ? people : people.filter(person => roster.includes(personKey(person))), [people, roster])
  const planningPeople = useMemo(() => rosterPeople.map(person => {
    const snapshot = velocityContext?.upcoming_capacity ?? null
    const capacity = capacityForPerson(snapshot, person)
    return { ...person, areas: [ANY_AREA], working_days: capacity ? snapshot?.working_days ?? 0 : 0,
      pto_days: capacity?.days_off ?? 0, capacity_points: undefined, focus_factor: undefined }
  }), [rosterPeople, velocityContext])
  const currentRoster = useRef({ people, roster })
  currentRoster.current = { people, roster }
  const inputsKey = JSON.stringify([scope, fromId, toId, perPerson, activeDays, sprintGoal, capacityMode, types, peopleForPlan(planningPeople), rosterEditorOpen, loadingSetup, velocityContext, loadingCapacity])
  const latestInputs = useRef(inputsKey)
  latestInputs.current = inputsKey
  const plan = planKey === inputsKey ? savedPlan : null
  const visibleFlagged = plan?.flagged.filter(story => attentionFilter === 'all' || story.flags.some(flag => flag.code === attentionFilter)) ?? []
  const rankedBacklog = useMemo(() => plan ? rankGoalBacklog(plan.available_backlog ?? plan.unplaced.map(item => item.story), plan.sprint_goal ?? sprintGoal) : [], [plan, sprintGoal])
  useEffect(() => {
    latestPlan.current += 1
    setPlan(null); setPlanKey(null); setCommitResult(null); setCommitModalOpen(false); setPlanning(false); setError('')
  }, [inputsKey])
  useEffect(() => () => { latestPlan.current += 1 }, [])


  useEffect(() => {
    if (!org || !project) { setTeams([]); setTeam(''); return }
    setTeam(readSavedTeam(org, project))
    let current = true
    api.teams(org, project, pat || undefined).then(list => current && setTeams(list)).catch(() => current && setTeams([]))
    return () => { current = false }
  }, [org, project, pat])

  const loadSetup = useCallback(async () => {
    const ticket = ++latestSetup.current
    setSetup(null)
    setupScope.current = ''
    setRoster(null); setRosterEditorOpen(false); setRosterDraft([]); setRosterSearch(''); setRosterError(''); setRosterNotice('')
    if (!ready) { setLoadingSetup(false); return }
    setLoadingSetup(true)
    setSetupError('')
    try {
      const found = await api.sprintPlanningSetup(org, project, team, pat || undefined)
      if (ticket !== latestSetup.current) return
      const savedRoster = loadRoster(org, project, team)
      setupScope.current = scope
      setSetup(found)
      const targetToId = found.default_to_id ?? ''
      setToId(targetToId)
      const allSprints = found.sprints ?? []
      const tIdx = allSprints.findIndex(s => s.id === targetToId)
      if (tIdx > 0) {
        setFromId(allSprints[tIdx - 1].id)
      } else {
        setFromId(found.default_from_id ?? '')
      }
      setPerPerson(found.per_person || DEFAULT_PER_PERSON)
      setActiveDays(found.active_days || DEFAULT_ACTIVE_DAYS)
      setTypes(found.default_types)
      setPeople(mergeRosterMembers(loadPeople(org, project, team), found.members, savedRoster))
      setRoster(savedRoster)
      setPlan(null)
      setCommitResult(null)
    } catch (e) {
      if (ticket === latestSetup.current) { setSetup(null); setSetupError(errorText(e)) }
    } finally {
      if (ticket === latestSetup.current) setLoadingSetup(false)
    }
  }, [ready, org, project, team, pat])

  useEffect(() => { void loadSetup(); return () => { latestSetup.current += 1 } }, [loadSetup])

  const capacityTeamId = teams.find(choice => choice.name === team || choice.id === team)?.id
  const refreshCapacity = useCallback(async () => {
    const ticket = ++latestCapacity.current
    latestPlan.current += 1
    setPlan(null); setPlanKey(null); setCommitResult(null); setCommitModalOpen(false); setPlanning(false)
    setVelocityContext(null); setCapacityError('')
    if (!ready || !toId || !capacityTeamId) { setLoadingCapacity(false); return }
    setLoadingCapacity(true)
    try {
      const context = await api.sprintVelocityContext(org, project, team, toId, pat || undefined)
      if (ticket !== latestCapacity.current) return
      setVelocityContext(withSavedCapacity(context, org, project, capacityTeamId))
    } catch (e) {
      if (ticket === latestCapacity.current) setCapacityError(`Capacity data could not be loaded: ${errorText(e)}`)
    } finally {
      if (ticket === latestCapacity.current) setLoadingCapacity(false)
    }
  }, [ready, org, project, team, toId, pat, capacityTeamId])
  useEffect(() => {
    void refreshCapacity()
    const refresh = (event: Event) => {
      if (event instanceof StorageEvent && event.key !== null && !event.key.startsWith('ado_sprint_capacity')) return
      if (commitInFlight.current) { capacityRefreshPending.current = true; return }
      void refreshCapacity()
    }
    window.addEventListener('storage', refresh)
    window.addEventListener('sprint-capacity-changed', refresh)
    return () => { latestCapacity.current += 1; window.removeEventListener('storage', refresh); window.removeEventListener('sprint-capacity-changed', refresh) }
  }, [refreshCapacity])

  const refreshMembers = async () => {
    if (loadingSetup || committing || setupScope.current !== scope) return
    const ticket = ++latestSetup.current
    latestPlan.current += 1
    setPlan(null); setPlanKey(null); setCommitModalOpen(false); setCommitResult(null)
    setLoadingSetup(true); setRosterError(''); setRosterNotice('')
    try {
      const found = await api.sprintPlanningSetup(org, project, team, pat || undefined)
      if (ticket !== latestSetup.current) return
      const current = currentRoster.current
      setPeople(mergeRosterMembers(current.people, found.members, current.roster))
      setSetup(previous => previous ? { ...previous, members: found.members, notes: found.notes } : previous)
      setRosterNotice('Available people refreshed. Your saved roster and planning settings are unchanged.')
    } catch (e) {
      if (ticket === latestSetup.current) setRosterError(`Available people could not be refreshed: ${errorText(e)}`)
    } finally {
      if (ticket === latestSetup.current) setLoadingSetup(false)
    }
  }

  const openRosterEditor = () => {
    setRosterDraft(roster ?? people.map(personKey))
    setRosterSearch(''); setRosterError(''); setRosterNotice(''); setRosterEditorOpen(true)
  }

  const saveTeamRoster = () => {
    const available = new Set(people.map(personKey))
    const selected = [...new Set(rosterDraft)].filter(key => available.has(key))
    try {
      saveRoster(org, project, team, selected)
      setRoster(selected); setRosterEditorOpen(false); setRosterError('')
      setRosterNotice('Team roster saved in this browser for this organization, project and team.')
    } catch {
      setRosterError('The team roster could not be saved in this browser. Check browser storage permissions and try again. Your previous roster is unchanged.')
    }
  }

  // Capacity preferences are kept in this browser for this team.
  useEffect(() => { if (setup && ready && setupScope.current === scope) savePeople(org, project, team, people) }, [people, setup, ready, org, project, team, scope])

  const changeTeam = (value: string) => {
    setTeam(value)
    setPlan(null)
    setCommitResult(null)
    try { localStorage.setItem(teamKey(org, project), value) } catch { /* storage blocked */ }
  }

  const sprints: PlanSprint[] = setup?.sprints ?? []
  const toSprint = sprints.find(s => s.id === toId)
  const fromSprint = sprints.find(s => s.id === fromId)

  const handlePlanSprintChange = (newToId: string) => {
    setToId(newToId)
    const idx = sprints.findIndex(s => s.id === newToId)
    if (idx > 0) {
      setFromId(sprints[idx - 1].id)
    } else {
      setFromId('')
    }
  }

  const problems = useMemo(() => planProblems(planningPeople, toId, fromId), [planningPeople, toId, fromId])

  const makePlan = async () => {
    if (committing || planning || loadingSetup || loadingCapacity || !velocityContext || rosterEditorOpen || problems.blocking.length) return
    const ticket = ++latestPlan.current
    const key = inputsKey
    setPlan(null); setPlanKey(null)
    setPlanning(true)
    setAttentionFilter('all')
    setError('')
    setCommitResult(null)
    try {
      const result = await api.sprintPlan({
        organization: org, project, team, pat: pat || undefined, from_iteration_id: fromId, to_iteration_id: toId, people: peopleForPlan(planningPeople),
        per_person: perPerson, active_days: activeDays, work_item_types: types.length ? types : undefined,
        sprint_goal: sprintGoal.trim() || undefined, capacity_mode: capacityMode,
        velocity_capacity: velocityCapacityInput(velocityContext),
      })
      if (result.project !== project || result.team !== team || result.to_sprint.id !== toId) {
        throw new Error('The returned plan does not match the selected project, team and sprint. Generate the plan again.')
      }
      if (ticket === latestPlan.current && latestInputs.current === key) { setPlan(result); setPlanKey(key) }
    } catch (e) {
      if (ticket === latestPlan.current && latestInputs.current === key) setError(errorText(e))
    } finally {
      if (ticket === latestPlan.current) setPlanning(false)
    }
  }

  const copyPlan = async () => {
    if (!plan) return
    try {
      await navigator.clipboard.writeText(planAsMarkdown(plan))
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch { setError('The plan could not be copied. Select the text on the page instead.') }
  }

  // Reassignment updates the complete draft atomically and preserves its source lane.
  const handleReassign = (storyId: number, targetKey: string) => {
    if (!plan || committing) return
    setPlan(current => current ? reassignStory(current, storyId, targetKey) : current)
    setCommitResult(null)
  }

  // Commit Plan to Azure DevOps
  const executeCommit = async () => {
    if (!plan || planning || commitInFlight.current || problems.blocking.length) return
    const key = inputsKey
    commitInFlight.current = true
    setCommitting(true)
    setCommitResult(null)
    setError('')
    try {
      const assignments = commitAssignments(plan)
      if (!assignments.length) throw new Error('There are no planned work items to commit.')
      const res = await api.sprintCommit({
        organization: org,
        project,
        team,
        pat: pat || undefined,
        to_iteration_id: plan.to_sprint.id,
        to_iteration_path: plan.to_sprint.path,
        assignments,
        sprint_goal: plan.sprint_goal || undefined,
      })
      if (latestInputs.current === key) { setCommitResult(res); setCommitModalOpen(false) }
    } catch (e) {
      if (latestInputs.current === key) setError(errorText(e))
    } finally {
      commitInFlight.current = false
      setCommitting(false)
      if (capacityRefreshPending.current) {
        capacityRefreshPending.current = false
        void refreshCapacity()
      }
    }
  }

  return (
    <fieldset className="sppPage" disabled={committing} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }} data-testid="sprint-planning-page">
      <div className="sppBanner">
        <div className="sppBannerIcon"><CalendarCheck size={22} /></div>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
            <h2>Sprint Planning Studio</h2>
            <div className="sppModeSwitcher">
              <button
                type="button"
                className={`sppModeBtn ${capacityMode === 'points' ? 'active' : ''}`}
                onClick={() => setCapacityMode('points')}
              >
                Points Capacity
              </button>
              <button
                type="button"
                className={`sppModeBtn ${capacityMode === 'stories' ? 'active' : ''}`}
                onClick={() => setCapacityMode('stories')}
              >
                Story Count
              </button>
            </div>
          </div>
          <p>Plan work based on points velocity and individual usable capacity. Flags carry-overs with blocked status and stale dwell times. Simulate workload balancing interactively and commit directly to Azure DevOps.</p>
        </div>
      </div>

      <div className="prToolbar sppToolbar">
        <div className="prToolbarLeft">
          <div className="prToolbarItem"><span className="prToolbarLabel">Org:</span>
            <input type="text" className="prOrgInput" placeholder="Organization" value={organization} onChange={e => onOrganizationChange?.(e.target.value)} /></div>
          <div className="prToolbarItem"><span className="prToolbarLabel">PAT:</span>
            <input type="password" className="prPatInput" placeholder={pat ? '••••••••••••••••' : 'PAT Token'} value={pat} onChange={e => onPatChange?.(e.target.value)} /></div>
          <div className="prToolbarItem"><span className="prToolbarLabel">Project:</span>
            <div className="prCustomSelectWrapper">
              <select className="prCustomSelect" value={project} onChange={e => onProjectChange?.(e.target.value)} data-testid="spp-project">
                <option value="">Select Project</option>
                {projects.map(p => <option key={p.id} value={p.name}>{p.name}</option>)}
              </select><ChevronDown size={14} className="prSelectArrow" />
            </div></div>
          <div className="prToolbarItem"><span className="prToolbarLabel">Team:</span>
            <div className="prCustomSelectWrapper">
              <select className="prCustomSelect" value={team} onChange={e => changeTeam(e.target.value)} data-testid="spp-team">
                <option value="">Select Team</option>
                {team && !teams.some(t => t.name === team) && <option value={team}>{team}</option>}
                {teams.map(t => <option key={t.id} value={t.name}>{t.name}</option>)}
              </select><ChevronDown size={14} className="prSelectArrow" />
            </div></div>
        </div>
      </div>

      {!ready && <div className="sppNotice" data-testid="spp-need-team"><Info size={14} /> Enter an organization, select a project and a team to begin.</div>}
      {setupError && <div className="sppNotice error" data-testid="spp-setup-error"><TriangleAlert size={14} /> {setupError}</div>}
      {loadingSetup && <div className="sppNotice"><Info size={14} /> Reading the team's sprints, members and areas…</div>}
      {setup?.notes.map(n => <div key={n} className="sppNotice warn" data-testid="spp-setup-note"><TriangleAlert size={14} /> {n}</div>)}
      {commitResult && (
        <div className={`sppNotice ${commitResult.success ? '' : 'warn'}`}>
          <div data-testid="spp-commit-result">
            {commitResult.success ? <Check size={14} /> : <TriangleAlert size={14} />} {commitResult.message}
            {commitResult.errors.length > 0 && <><p>These work items were not updated. Review the errors before retrying the plan.</p><ul>{commitResult.errors.map((message, i) => <li key={i}>{message}</li>)}</ul></>}
          </div>
        </div>
      )}

      {setup && (
        <>
          <div className="sppGoalBar">
            <span className="sppGoalLabel"><Target size={14} /> Sprint Goal</span>
            <input
              type="text"
              className="sppGoalInput"
              placeholder="e.g. Deliver OAuth 2.0 Auth Flow & Resolve High-Priority Latency Bugs"
              value={sprintGoal}
              onChange={e => setSprintGoal(e.target.value)}
            />
          </div>

          <section className="sppCard" data-testid="spp-settings">
            <div className="sppCardHead"><div><h3>Sprints and rules</h3><p>Stories still open in the previous sprint move to the planned sprint with their previous assignees.</p></div></div>
            <div className="sppSettings">
              <label>Plan sprint
                <select value={toId} onChange={e => handlePlanSprintChange(e.target.value)} data-testid="spp-to">
                  <option value="">Choose a sprint</option>
                  {sprints.map(s => <option key={s.id} value={s.id}>{sprintLabel(s)}</option>)}
                </select>
                {fromSprint && (
                  <span style={{ fontSize: '11px', color: 'var(--spp-muted)', marginTop: '4px', display: 'block' }}>
                    Auto-checking carryovers from: <b>{fromSprint.name}</b>
                  </span>
                )}
              </label>
              <label>Story count reference (display only)
                <input type="number" min={MIN_PER_PERSON} max={MAX_PER_PERSON} value={perPerson} data-testid="spp-per-person"
                  onChange={e => setPerPerson(Math.max(MIN_PER_PERSON, Math.min(MAX_PER_PERSON, Number(e.target.value) || DEFAULT_PER_PERSON)))} /></label>
              <label>Flag when active for more than (days)
                <input type="number" min={1} max={90} value={activeDays} data-testid="spp-active-days"
                  onChange={e => setActiveDays(Math.max(1, Math.min(90, Number(e.target.value) || DEFAULT_ACTIVE_DAYS)))} /></label>
            </div>
          </section>

          <section className="sppCard" data-testid="spp-people">
            <div className="sppCardHead">
              <div><h3><Users size={15} /> Team Capacity</h3>
                <p>Working Days, PTO and hours come from the Capacity tab for the planned sprint. Edit availability there, not here. Assignments use each person's previous completed points scaled by available days; hours are never converted to points.</p></div>
              <div className="sppRosterActions">
                <button type="button" className="sppGhost" onClick={openRosterEditor} disabled={loadingSetup || rosterEditorOpen} data-testid="spp-edit-roster">Edit team roster</button>
                <button type="button" className="sppGhost" onClick={() => void refreshMembers()} disabled={loadingSetup} data-testid="spp-refresh-members">Refresh available people</button>
                <button type="button" className="sppGhost" onClick={() => void refreshCapacity()} disabled={loadingCapacity} data-testid="spp-refresh-capacity">Refresh Capacity data</button>
              </div>
              {loadingCapacity && <p className="sppMuted" role="status">Reading Capacity data…</p>}
              {capacityError && <p className="sppNotice error" role="alert">{capacityError}</p>}
              {velocityContext && <p className="sppMuted" data-testid="spp-velocity-baseline">
                Historical baseline: {velocityContext.previous?.name ?? 'No previous completed sprint'}.
                {' '}Budget = previous completed points × upcoming available days ÷ previous available days.
                {' '}Carryover is assumed 50% complete. Unknown history or availability pauses automatic new assignments, but manual draft assignment remains available.
              </p>}
              {velocityContext?.notes.map(note => <p key={note} className="sppMuted">{note}</p>)}
            </div>
            {rosterError && <div role="alert" className="sppNotice error" data-testid="spp-roster-error"><TriangleAlert size={14} /> {rosterError}</div>}
            {rosterNotice && <p role="status" className="sppMuted">{rosterNotice}</p>}
            {rosterEditorOpen && (
              <div className="sppRosterEditor" data-testid="spp-roster-editor">
                <h4>Choose the members of {team}</h4>
                <p className="sppMuted">Available people include members across all teams in this project. This changes your local planning roster only, not Azure DevOps team membership.</p>
                <input type="search" className="sppRosterSearch" value={rosterSearch} onChange={e => setRosterSearch(e.target.value)}
                  placeholder="Search by name or email" aria-label="Search roster candidates" />
                <div className="sppRosterChoices">
                  {people.filter(person => `${person.name} ${person.unique_name}`.toLowerCase().includes(rosterSearch.trim().toLowerCase())).map(person => {
                    const key = personKey(person)
                    return (
                      <label key={key} className="sppRosterChoice">
                        <input type="checkbox" checked={rosterDraft.includes(key)} disabled={loadingSetup}
                          onChange={e => setRosterDraft(selected => e.target.checked ? [...selected, key] : selected.filter(value => value !== key))}
                          aria-label={`Roster ${person.name}`} />
                        <span>{person.name}{person.unique_name && <small>{person.unique_name}</small>}</span>
                      </label>
                    )
                  })}
                </div>
                {!people.some(person => `${person.name} ${person.unique_name}`.toLowerCase().includes(rosterSearch.trim().toLowerCase())) &&
                  <p className="sppMuted">No matching people. Add someone by name or email below.</p>}
                <div className="sppRosterActions">
                  <button type="button" className="sppGhost" onClick={() => setRosterDraft(people.map(personKey))} disabled={loadingSetup}>Select all</button>
                  <button type="button" className="sppGhost" onClick={() => setRosterDraft([])} disabled={loadingSetup}>Clear selection</button>
                  <button type="button" className="sppGhost" onClick={() => { setRosterEditorOpen(false); setRosterError('') }} disabled={loadingSetup}>Cancel</button>
                  <button type="button" className="sppPrimary" onClick={saveTeamRoster} disabled={loadingSetup} data-testid="spp-save-roster">Save team roster ({rosterDraft.length})</button>
                </div>
              </div>
            )}
            {roster !== null && <p className="sppMuted" data-testid="spp-roster-summary">{rosterPeople.length} saved team members. Use Edit team roster to change this list.</p>}
            <div className="sppTableWrap">
            <table className="sppTable">
              <thead>
                <tr>
                  <th>In plan</th>
                  <th>Person</th>
                  <th>Working Days</th>
                  <th>PTO</th>
                  <th>Total Capacity (h)</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rosterPeople.map(p => {
                  const key = personKey(p)
                  const snapshot = velocityContext?.upcoming_capacity ?? null
                  const capacity = capacityForPerson(snapshot, p)
                  return (
                    <tr key={key} className={p.included ? '' : 'off'} data-testid={`spp-person-${key}`}>
                      <td><input type="checkbox" checked={p.included} onChange={e => setPeople(setIncluded(people, key, e.target.checked))} aria-label={`Plan ${p.name}`} /></td>
                      <td><b>{p.name}</b>{p.unique_name && <small>{p.unique_name}</small>}</td>
                      <td data-label="Working Days">
                        <span data-testid={`spp-days-${key}`}>{snapshot ? snapshot.working_days : 'Unavailable'}</span>
                      </td>
                      <td data-label="PTO">
                        <span data-testid={`spp-pto-${key}`}>{capacity ? capacity.days_off : 'Unavailable'}</span>
                      </td>
                      <td data-label="Total Capacity (h)" data-testid={`spp-hours-${key}`}>{capacity && snapshot ? totalCapacityHours(snapshot.working_days, capacity) : 'Unavailable'}</td>
                      <td>{p.manual && <button type="button" className="sppIconBtn" onClick={() => setPeople(removePerson(people, key))} aria-label={`Remove ${p.name}`}><X size={13} /></button>}</td>
                    </tr>
                  )
                })}
                {rosterPeople.length === 0 && <tr><td colSpan={6} className="sppMuted">{roster === null ? 'The team has no members listed. Add people below.' : 'The saved team roster is empty. Use Edit team roster to select people.'}</td></tr>}
              </tbody>
            </table>
            </div>
            <div className="sppAddPerson">
              <input value={newPerson} onChange={e => setNewPerson(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') { setPeople(addPerson(people, newPerson)); setNewPerson('') } }}
                placeholder="Add someone by name or email" aria-label="Add someone by name or email" data-testid="spp-add-person" />
              <button type="button" onClick={() => { setPeople(addPerson(people, newPerson)); setNewPerson('') }} disabled={!newPerson.trim()}><Plus size={13} /> Add</button>
            </div>
            {roster !== null && <p className="sppMuted">People added above become available candidates. Select them in Edit team roster to include them.</p>}
          </section>

          <div className="sppActions">
            <button type="button" className="sppPrimary" onClick={() => void makePlan()} disabled={planning || committing || loadingSetup || loadingCapacity || !velocityContext || rosterEditorOpen || problems.blocking.length > 0} data-testid="spp-plan">
              <CalendarCheck size={14} /> {planning ? 'Planning…' : toSprint ? `Plan ${toSprint.name}` : 'Plan the sprint'}
            </button>
            {plan && (
              <>
                <button type="button" className="sppGhost" onClick={() => void copyPlan()} data-testid="spp-copy">
                  {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? 'Copied' : 'Copy plan'}
                </button>
                <button type="button" className="sppPrimary" style={{ background: '#059669', borderColor: '#059669' }} onClick={() => setCommitModalOpen(true)} disabled={planning || committing || problems.blocking.length > 0 || !plan.summary.stories_planned}>
                  <Send size={14} /> Commit to Azure DevOps
                </button>
              </>
            )}
            <div className="sppHints">
              {problems.blocking.map(b => <span key={b} className="sppMuted" data-testid="spp-blocking">{b}</span>)}
              {problems.warnings.map(w => <span key={w} className="sppWarn" data-testid="spp-warning"><TriangleAlert size={12} /> {w}</span>)}
            </div>
          </div>
          {error && <div className="sppNotice error" data-testid="spp-error"><TriangleAlert size={14} /> {error}</div>}
        </>
      )}

      {plan && (
        <div className="sppResult" data-testid="spp-result">
          {/* AI Copilot & Risk Section */}
          <div className="sppAiSection">
            <div className="sppAiHead">
              <div className="sppAiTitle">
                <Sparkles size={16} color="#818cf8" />
                <span>AI Sprint Insights & Risk Assessment</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span className={`sppRiskBadge ${(plan.summary.risk_score || 'low').toLowerCase()}`}>
                  <ShieldAlert size={12} /> Risk: {plan.summary.risk_score || 'Low'}
                </span>
                <span className="sppChip" style={{ fontWeight: 600 }}>
                  Confidence: {plan.summary.sprint_confidence_pct ?? 85}%
                </span>
              </div>
            </div>
            {plan.summary.risk_reasons && plan.summary.risk_reasons.length > 0 && (
              <ul className="sppReasons" style={{ margin: 0 }}>
                {plan.summary.risk_reasons.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            )}
            {plan.ai_recommendations && plan.ai_recommendations.length > 0 && (
              <ul className="sppAiRecsList">
                {plan.ai_recommendations.map((rec, i) => (
                  <li key={i} className="sppAiRecItem">
                    <Bot size={15} color="#818cf8" style={{ flexShrink: 0, marginTop: '1px' }} />
                    <span>{rec}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="sppKpis" data-testid="spp-summary">
            <Kpi label="People" value={plan.summary.people} testId="spp-kpi-people" />
            <Kpi
              label={plan.people.some(p => p.velocity_based) ? 'Reserved workload' : 'Points Planned'}
              value={`${plan.people.some(p => p.velocity_based) ? plan.summary.total_points_reserved ?? 0 : plan.summary.total_points_planned ?? 0} pts`}
              sub={`Forecast: ${plan.summary.total_points_capacity ?? 0} pts · Original story size: ${plan.summary.total_points_planned ?? 0} pts`}
              testId="spp-kpi-planned"
            />
            <Kpi label="Stories planned" value={plan.summary.stories_planned} sub="Individual velocity-based assignments" testId="spp-kpi-stories" />
            <Kpi label="Carried over" value={`${plan.summary.carried} (${plan.summary.points_carried ?? 0} pts)`} testId="spp-kpi-carried" />
            <Kpi label="New from backlog" value={`${plan.summary.new} (${plan.summary.points_new ?? 0} pts)`} testId="spp-kpi-new" />
            <Kpi label="Need a look" value={plan.summary.flagged} sub={`${plan.summary.blocked} blocked · ${plan.summary.long_active} active > ${plan.active_days}d`} tone={plan.summary.flagged ? 'warn' : undefined} testId="spp-kpi-flagged" />
            {plan.people.some(p => p.velocity_based)
              ? <Kpi label="Unallocated forecast" value={`${Math.round(plan.people.reduce((sum, p) => sum + (p.points_open ?? 0), 0) * 100) / 100} pts`} testId="spp-kpi-open" />
              : <Kpi label="Empty places" value={plan.summary.open_places} tone={plan.summary.open_places ? 'warn' : undefined} testId="spp-kpi-open" />}
          </div>

          {plan.notes.map(n => <div key={n} className="sppNotice warn" data-testid="spp-note"><TriangleAlert size={14} /> {n}</div>)}

          {plan.flagged.length > 0 && (
            <section className="sppCard attention" data-testid="spp-flagged">
              <div className="sppCardHead"><div><h3><TriangleAlert size={15} /> Look at these first ({plan.flagged.length})</h3>
                <p>Carried over, and blocked or active for more than {plan.active_days} days. Select View Recent Comments to read their last 3 comments.</p></div></div>
              <div className="sppRosterActions">
                <label className="sppMuted">Show{' '}
                  <select className="sppReassignSelect" value={attentionFilter} onChange={event => setAttentionFilter(event.target.value)} aria-label="Filter stories needing attention">
                    <option value="all">All</option>
                    <option value="blocked">Blocked</option>
                    <option value="active_too_long">Active too long</option>
                  </select>
                </label>
                <span className="sppMuted" role="status">Showing {visibleFlagged.length} of {plan.flagged.length}</span>
              </div>
              <div className="sppFlaggedList">
                {visibleFlagged.map(s => (
                  <FlaggedCard
                    key={s.id}
                    story={s}
                    project={project}
                    loadComments={loadComments}
                    onDrop={id => handleReassign(id, '')}
                  />
                ))}
              </div>
              {visibleFlagged.length === 0 && <p className="sppMuted">No stories match this attention filter.</p>}
            </section>
          )}

          <section data-testid="spp-people-plan">
            <h3 className="sppH">Team Workload Swimlanes for {plan.to_sprint.name}</h3>
            <div className="sppPlanningPanes">
              <section className="sppWorkloadPane" aria-label="Planned team workloads" data-testid="spp-workload-pane">
                <h4>Team workloads</h4>
                <p className="sppMuted">Carryover, existing sprint commitments and automatically planned work. Assignment changes update this draft only.</p>
                <div className="sppPeople">
                  {plan.people.map(p => (
                    <PersonCard
                      key={personKey(p)}
                      person={p}
                      loadComments={loadComments}
                      sprintName={plan.to_sprint.name}
                      project={project}
                      mode={capacityMode}
                      allPeople={plan.people}
                      onReassign={handleReassign}
                    />
                  ))}
                </div>
              </section>
              <section className="sppCard sppBacklogPane" aria-label="Available backlog" data-testid="spp-unplaced">
                <div className="sppCardHead"><div><h3>Available backlog ({rankedBacklog.length})</h3>
                  <p>Remaining work from this team's scope. Sprint Goal topic matches appear first. Select a team member to add an item to their workload.</p>
                  <p className="sppMuted">Separate goal topics with commas or "and". Matches require a topic phrase; single-word topics must appear in the title or a tag. Equal matches retain backlog order. The planner reads up to 300 backlog candidates.</p>
                </div></div>
                <ul className="sppUnplaced">
                  {rankedBacklog.map(({ story, matches, evidence }) => (
                    <StoryRow
                      key={story.id}
                      story={story}
                      project={project}
                      loadComments={loadComments}
                      note={plan.unplaced.find(item => item.story.id === story.id)?.reason}
                      goalMatches={matches}
                      goalEvidence={evidence}
                      people={plan.people}
                      onReassign={handleReassign}
                    />
                  ))}
                </ul>
                {rankedBacklog.length === 0 && <p className="sppMuted">No remaining backlog items in the candidates read for this plan.</p>}
              </section>
            </div>
          </section>

          {plan.outside_plan.length > 0 && (
            <section className="sppCard" data-testid="spp-outside">
              <div className="sppCardHead"><div><h3>Open stories of people who are not in this plan ({plan.outside_plan.length})</h3><p>Not counted for anyone.</p></div></div>
              <ul>{plan.outside_plan.map(s => <StoryRow key={s.id} story={s} project={project} loadComments={loadComments} note={s.assigned_to} />)}</ul>
            </section>
          )}

          <p className="sppFoot" data-testid="spp-foot">Made {plan.generated_at.replace('T', ' ').replace('Z', ' UTC')}. Use "Commit to Azure DevOps" to write assignments to ADO.</p>
        </div>
      )}

      {/* Commit Confirmation Modal */}
      {commitModalOpen && plan && toSprint && (
        <div className="sppModalBackdrop" onClick={() => setCommitModalOpen(false)}>
          <div className="sppModalContent" onClick={e => e.stopPropagation()}>
            <div className="sppModalHead">
              <h3>Commit Sprint Plan to Azure DevOps</h3>
              <button type="button" className="sppIconBtn" onClick={() => setCommitModalOpen(false)}><X size={15} /></button>
            </div>
            <p style={{ margin: 0, fontSize: '13px', color: 'var(--spp-muted)' }}>
              This will update <b>{plan.people.reduce((a, b) => a + b.total, 0)}</b> work items directly in Azure DevOps to iteration <b>{plan.to_sprint.name}</b> (`{plan.to_sprint.path}`) and assign them to their respective team members.
            </p>
            {sprintGoal && (
              <div style={{ background: 'var(--spp-field)', padding: '8px 12px', borderRadius: '8px', fontSize: '12px' }}>
                <b>Sprint Goal:</b> {sprintGoal}
              </div>
            )}
            <div className="sppModalFoot">
              <button type="button" className="sppGhost" onClick={() => setCommitModalOpen(false)}>Cancel</button>
              <button type="button" className="sppPrimary" onClick={() => void executeCommit()} disabled={committing}>
                {committing ? 'Committing…' : 'Confirm & Commit'}
              </button>
            </div>
          </div>
        </div>
      )}
    </fieldset>
  )
}


export const SprintPlanningPage = LegacySprintPlanningPage
