import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Ban, CalendarCheck, Check, ChevronDown, Clock, Copy, ExternalLink, Info, Plus, TriangleAlert, Users, X } from 'lucide-react'
import './SprintPlanningPage.css'
import { api } from '../services/api'
import type { AdoTeam, PlanSprint, PlanStory, PlannedPerson, SprintPlan, SprintPlanningSetup } from '../types/api'
import {
  ANY_AREA, DEFAULT_ACTIVE_DAYS, DEFAULT_PER_PERSON, MAX_PER_PERSON, MIN_PER_PERSON,
  addPerson, areaLabel, commentDate, daysInState, flagText, fullness, loadPeople, mergeMembers, peopleForPlan, personKey, plural, planAsMarkdown, planProblems,
  removePerson, savePeople, setAreas, setIncluded, sprintLabel, storyCount,
  type PlanningPerson,
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

// ---------------------------------------------------------------- an area picker for one person

const AreaPicker: React.FC<{ value: string[]; options: string[]; project: string; onChange: (areas: string[]) => void; testId: string }> = ({ value, options, project, onChange, testId }) => {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => { if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])
  const choices = [ANY_AREA, ...options, ...value.filter(v => v !== ANY_AREA && !options.includes(v))]
  const toggle = (area: string) => onChange(value.includes(area) ? value.filter(a => a !== area) : [...value, area])
  const addDraft = () => {
    const path = draft.trim()
    if (path && !value.includes(path)) onChange([...value, path])
    setDraft('')
  }
  const summary = !value.length ? 'Choose areas' : value.length === 1 ? areaLabel(value[0], project) : `${areaLabel(value[0], project)} +${value.length - 1}`
  return (
    <div className="sppPicker" ref={ref}>
      <button type="button" className={`sppPickerBtn ${value.length ? '' : 'needsAreas'}`} onClick={() => setOpen(o => !o)} aria-expanded={open} data-testid={testId} title={value.map(v => areaLabel(v, project)).join(', ')}>
        <span>{summary}</span><ChevronDown size={13} />
      </button>
      {open && (
        <div className="sppPickerMenu" role="listbox" aria-label="Areas of choice">
          <div className="sppPickerList">
            {choices.map(area => (
              <label key={area} className="sppPickerOption">
                <input type="checkbox" checked={value.includes(area)} onChange={() => toggle(area)} />
                <span>{areaLabel(area, project)}</span>
              </label>
            ))}
          </div>
          <div className="sppPickerAdd">
            <input value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={e => e.key === 'Enter' && addDraft()} placeholder="Add an area path" aria-label="Add an area path" />
            <button type="button" onClick={addDraft} disabled={!draft.trim()} aria-label="Add area"><Plus size={13} /></button>
          </div>
          <div className="sppPickerFoot">
            <button type="button" onClick={() => onChange([])} disabled={!value.length}>Clear</button>
            <button type="button" onClick={() => setOpen(false)}>Done</button>
          </div>
        </div>
      )}
    </div>
  )
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

const StoryRow: React.FC<{ story: PlanStory; project: string; note?: string }> = ({ story, project, note }) => (
  <li className="sppStory" data-testid={`spp-story-${story.id}`}>
    <a href={workItemUrl(story)} target="_blank" rel="noreferrer" className="sppStoryTitle">
      <span className="sppId">#{story.id}</span> {story.title}<ExternalLink size={10} />
    </a>
    <div className="sppStoryMeta">
      <span className="sppChip">{story.state}</span>
      <FlagChips story={story} />
      {story.points !== null && <span className="sppChip">{story.points} pts</span>}
      <span className="sppArea" title={story.area_path}>{areaLabel(story.area_path, project)}</span>
      {note && <span className="sppNote">{note}</span>}
    </div>
  </li>
)

const FlaggedCard: React.FC<{ story: PlanStory; project: string }> = ({ story, project }) => (
  <article className="sppFlagged" data-testid={`spp-flagged-${story.id}`}>
    <div className="sppFlaggedHead">
      <a href={workItemUrl(story)} target="_blank" rel="noreferrer" className="sppStoryTitle"><span className="sppId">#{story.id}</span> {story.title}<ExternalLink size={10} /></a>
      <div className="sppStoryMeta">
        <span className="sppOwner">{story.assigned_to || 'Nobody'}</span>
        <span className="sppChip">{story.state}{daysInState(story) ? ` · ${daysInState(story)}` : ''}</span>
        <FlagChips story={story} />
        <span className="sppArea" title={story.area_path}>{areaLabel(story.area_path, project)}</span>
      </div>
      <ul className="sppReasons">{story.flags.map(f => <li key={f.code}>{f.reason}</li>)}</ul>
    </div>
    <div className="sppComments" data-testid={`spp-comments-${story.id}`}>
      <h5>Last {story.comments?.length ? plural(story.comments.length, 'comment') : 'comments'} <span>(oldest first)</span></h5>
      {story.comments === null && <p className="sppMuted">The comments could not be read.</p>}
      {story.comments?.length === 0 && <p className="sppMuted">No comments on this story.</p>}
      {story.comments?.map((c, i) => (
        <blockquote key={`${c.date}-${i}`} data-testid="spp-comment">
          <div className="sppCommentHead"><b>{c.author}</b><span>{commentDate(c.date)}</span></div>
          <p>{c.text}</p>
        </blockquote>
      ))}
    </div>
  </article>
)

const PersonCard: React.FC<{ person: PlannedPerson; sprintName: string; project: string }> = ({ person, sprintName, project }) => {
  const key = personKey(person)
  const percent = Math.min(100, Math.round((person.total / Math.max(1, person.capacity)) * 100))
  const state = person.over_by ? 'over' : person.open_places ? 'short' : 'full'
  return (
    <section className={`sppPerson ${state}`} data-testid={`spp-card-${key}`}>
      <div className="sppPersonHead">
        <div><h4>{person.name}</h4><span className="sppMuted">{person.areas.length ? person.areas.map(a => areaLabel(a, project)).join(', ') : 'No area of choice'}</span></div>
        <div className="sppFill" title={`${person.total} stories planned of ${person.capacity}`}>
          <b data-testid={`spp-count-${key}`}>{fullness(person)}</b>
          <span className="sppMeter"><span style={{ width: `${percent}%` }} /></span>
        </div>
      </div>
      {person.carried.length > 0 && <><h5>Carried over from the current sprint <span>({person.carried.length})</span></h5><ul>{person.carried.map(s => <StoryRow key={s.id} story={s} project={project} />)}</ul></>}
      {person.already_planned.length > 0 && <><h5>Already in {sprintName} <span>({person.already_planned.length})</span></h5><ul>{person.already_planned.map(s => <StoryRow key={s.id} story={s} project={project} />)}</ul></>}
      {person.new.length > 0 && <><h5>New from the backlog <span>({person.new.length})</span></h5><ul>{person.new.map(s => <StoryRow key={s.id} story={s} project={project} note={s.matched_area ? `area: ${areaLabel(s.matched_area, project)}` : undefined} />)}</ul></>}
      {storyCount(person) === 0 && <p className="sppMuted">No stories planned.</p>}
      {person.warnings.map(w => <p key={w} className="sppWarn" data-testid="spp-person-warning"><TriangleAlert size={12} /> {w}</p>)}
    </section>
  )
}

const Kpi: React.FC<{ label: string; value: number; sub?: string; tone?: 'warn' | 'bad'; testId: string }> = ({ label, value, sub, tone, testId }) => (
  <div className={`sppKpi ${tone ?? ''}`} data-testid={testId}><span>{label}</span><b>{value}</b>{sub && <small>{sub}</small>}</div>
)

// ---------------------------------------------------------------- the page

export const SprintPlanningPage: React.FC<SprintPlanningPageProps> = ({
  organization = '', project = '', pat = '', projects = [], onOrganizationChange, onProjectChange, onPatChange,
}) => {
  const org = organization.trim()
  const [teams, setTeams] = useState<AdoTeam[]>([])
  const [team, setTeam] = useState('')
  const [setup, setSetup] = useState<SprintPlanningSetup | null>(null)
  const [loadingSetup, setLoadingSetup] = useState(false)
  const [setupError, setSetupError] = useState('')
  const [fromId, setFromId] = useState('')
  const [toId, setToId] = useState('')
  const [perPerson, setPerPerson] = useState(DEFAULT_PER_PERSON)
  const [activeDays, setActiveDays] = useState(DEFAULT_ACTIVE_DAYS)
  const [types, setTypes] = useState<string[]>([])
  const [people, setPeople] = useState<PlanningPerson[]>([])
  const [newPerson, setNewPerson] = useState('')
  const [plan, setPlan] = useState<SprintPlan | null>(null)
  const [planning, setPlanning] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  const latestSetup = useRef(0)
  const ready = !!org && !!project && !!team

  useEffect(() => {
    if (!org || !project) { setTeams([]); setTeam(''); return }
    setTeam(readSavedTeam(org, project))
    let current = true
    api.teams(org, project, pat || undefined).then(list => current && setTeams(list)).catch(() => current && setTeams([]))
    return () => { current = false }
  }, [org, project, pat])

  const loadSetup = useCallback(async () => {
    if (!ready) { setSetup(null); return }
    const ticket = ++latestSetup.current
    setLoadingSetup(true)
    setSetupError('')
    try {
      const found = await api.sprintPlanningSetup(org, project, team, pat || undefined)
      if (ticket !== latestSetup.current) return
      setSetup(found)
      setFromId(found.default_from_id ?? '')
      setToId(found.default_to_id ?? '')
      setPerPerson(found.per_person || DEFAULT_PER_PERSON)
      setActiveDays(found.active_days || DEFAULT_ACTIVE_DAYS)
      setTypes(found.default_types)
      setPeople(mergeMembers(loadPeople(org, project, team), found.members))
      setPlan(null)
    } catch (e) {
      if (ticket === latestSetup.current) { setSetup(null); setSetupError(errorText(e)) }
    } finally {
      if (ticket === latestSetup.current) setLoadingSetup(false)
    }
  }, [ready, org, project, team, pat])

  useEffect(() => { void loadSetup() }, [loadSetup])

  // the areas people chose are kept in this browser for this team
  useEffect(() => { if (setup && ready) savePeople(org, project, team, people) }, [people, setup, ready, org, project, team])

  const changeTeam = (value: string) => {
    setTeam(value)
    setPlan(null)
    try { localStorage.setItem(teamKey(org, project), value) } catch { /* storage blocked */ }
  }

  const problems = useMemo(() => planProblems(people, fromId, toId), [people, fromId, toId])
  const sprints: PlanSprint[] = setup?.sprints ?? []
  const toSprint = sprints.find(s => s.id === toId)

  const makePlan = async () => {
    setPlanning(true)
    setError('')
    try {
      setPlan(await api.sprintPlan({
        organization: org, project, team, pat: pat || undefined, from_iteration_id: fromId, to_iteration_id: toId, people: peopleForPlan(people),
        per_person: perPerson, active_days: activeDays, work_item_types: types.length ? types : undefined,
      }))
    } catch (e) {
      setError(errorText(e))
    } finally {
      setPlanning(false)
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

  return (
    <div className="sppPage" data-testid="sprint-planning-page">
      <div className="sppBanner">
        <div className="sppBannerIcon"><CalendarCheck size={22} /></div>
        <div>
          <h2>Sprint Planning</h2>
          <p>Every person gets the same number of stories. Stories still open in the current sprint move with their owner and are flagged when they are blocked or have been active too long, with their last 3 comments. The free places are filled from the backlog by each person's area of choice. The plan is shown here only: nothing is changed in Azure DevOps.</p>
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

      {setup && (
        <>
          <section className="sppCard" data-testid="spp-settings">
            <div className="sppCardHead"><div><h3>Sprints and rules</h3><p>Stories still open in the first sprint move to the second one.</p></div></div>
            <div className="sppSettings">
              <label>Carry stories from
                <select value={fromId} onChange={e => setFromId(e.target.value)} data-testid="spp-from">
                  <option value="">Choose a sprint</option>
                  {sprints.map(s => <option key={s.id} value={s.id}>{sprintLabel(s)}</option>)}
                </select></label>
              <label>Plan sprint
                <select value={toId} onChange={e => setToId(e.target.value)} data-testid="spp-to">
                  <option value="">Choose a sprint</option>
                  {sprints.map(s => <option key={s.id} value={s.id}>{sprintLabel(s)}</option>)}
                </select></label>
              <label>Stories per person
                <input type="number" min={MIN_PER_PERSON} max={MAX_PER_PERSON} value={perPerson} data-testid="spp-per-person"
                  onChange={e => setPerPerson(Math.max(MIN_PER_PERSON, Math.min(MAX_PER_PERSON, Number(e.target.value) || DEFAULT_PER_PERSON)))} /></label>
              <label>Flag when active for more than (days)
                <input type="number" min={1} max={90} value={activeDays} data-testid="spp-active-days"
                  onChange={e => setActiveDays(Math.max(1, Math.min(90, Number(e.target.value) || DEFAULT_ACTIVE_DAYS)))} /></label>
              <fieldset className="sppTypes"><legend>Work item types</legend>
                {setup.work_item_types.map(t => (
                  <label key={t} className="sppCheck"><input type="checkbox" checked={types.includes(t)} onChange={() => setTypes(types.includes(t) ? types.filter(x => x !== t) : [...types, t])} /> {t}</label>
                ))}
              </fieldset>
            </div>
          </section>

          <section className="sppCard" data-testid="spp-people">
            <div className="sppCardHead">
              <div><h3><Users size={15} /> Who is in the plan, and their areas of choice</h3>
                <p>A person is given new stories only from the areas they choose (a story under a chosen area counts). Several people may share an area. Saved in this browser for this team.</p></div>
            </div>
            <div className="sppTableWrap">
            <table className="sppTable">
              <thead><tr><th>In plan</th><th>Person</th><th>Areas of choice</th><th /></tr></thead>
              <tbody>
                {people.map(p => {
                  const key = personKey(p)
                  return (
                    <tr key={key} className={p.included ? '' : 'off'} data-testid={`spp-person-${key}`}>
                      <td><input type="checkbox" checked={p.included} onChange={e => setPeople(setIncluded(people, key, e.target.checked))} aria-label={`Plan ${p.name}`} /></td>
                      <td><b>{p.name}</b>{p.unique_name && <small>{p.unique_name}</small>}</td>
                      <td><AreaPicker value={p.areas} options={setup.areas} project={project} onChange={areas => setPeople(setAreas(people, key, areas))} testId={`spp-areas-${key}`} /></td>
                      <td>{p.manual && <button type="button" className="sppIconBtn" onClick={() => setPeople(removePerson(people, key))} aria-label={`Remove ${p.name}`}><X size={13} /></button>}</td>
                    </tr>
                  )
                })}
                {people.length === 0 && <tr><td colSpan={4} className="sppMuted">The team has no members listed. Add people below.</td></tr>}
              </tbody>
            </table>
            </div>
            <div className="sppAddPerson">
              <input value={newPerson} onChange={e => setNewPerson(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') { setPeople(addPerson(people, newPerson)); setNewPerson('') } }}
                placeholder="Add someone by name or email" aria-label="Add someone by name or email" data-testid="spp-add-person" />
              <button type="button" onClick={() => { setPeople(addPerson(people, newPerson)); setNewPerson('') }} disabled={!newPerson.trim()}><Plus size={13} /> Add</button>
            </div>
          </section>

          <div className="sppActions">
            <button type="button" className="sppPrimary" onClick={() => void makePlan()} disabled={planning || problems.blocking.length > 0} data-testid="spp-plan">
              <CalendarCheck size={14} /> {planning ? 'Planning…' : toSprint ? `Plan ${toSprint.name}` : 'Plan the sprint'}
            </button>
            {plan && (
              <button type="button" className="sppGhost" onClick={() => void copyPlan()} data-testid="spp-copy">
                {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? 'Copied' : 'Copy plan'}
              </button>
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
          <div className="sppKpis" data-testid="spp-summary">
            <Kpi label="People" value={plan.summary.people} testId="spp-kpi-people" />
            <Kpi label="Stories planned" value={plan.summary.stories_planned} sub={`${plan.per_person} each`} testId="spp-kpi-planned" />
            <Kpi label="Carried over" value={plan.summary.carried} testId="spp-kpi-carried" />
            <Kpi label="New from backlog" value={plan.summary.new} testId="spp-kpi-new" />
            <Kpi label="Need a look" value={plan.summary.flagged} sub={`${plan.summary.blocked} blocked · ${plan.summary.long_active} active > ${plan.active_days} days`} tone={plan.summary.flagged ? 'warn' : undefined} testId="spp-kpi-flagged" />
            <Kpi label="Empty places" value={plan.summary.open_places} tone={plan.summary.open_places ? 'warn' : undefined} testId="spp-kpi-open" />
          </div>

          {plan.notes.map(n => <div key={n} className="sppNotice warn" data-testid="spp-note"><TriangleAlert size={14} /> {n}</div>)}

          {plan.flagged.length > 0 && (
            <section className="sppCard attention" data-testid="spp-flagged">
              <div className="sppCardHead"><div><h3><TriangleAlert size={15} /> Look at these first ({plan.flagged.length})</h3>
                <p>Carried over, and blocked or active for more than {plan.active_days} days. Their last 3 comments show where each one stands.</p></div></div>
              <div className="sppFlaggedList">{plan.flagged.map(s => <FlaggedCard key={s.id} story={s} project={project} />)}</div>
            </section>
          )}

          <section data-testid="spp-people-plan">
            <h3 className="sppH">Plan for {plan.to_sprint.name}</h3>
            <div className="sppPeople">{plan.people.map(p => <PersonCard key={personKey(p)} person={p} sprintName={plan.to_sprint.name} project={project} />)}</div>
          </section>

          {plan.unplaced_total > 0 && (
            <section className="sppCard" data-testid="spp-unplaced">
              <div className="sppCardHead"><div><h3>Not placed ({plan.unplaced_total})</h3><p>Backlog stories nobody could take.</p></div></div>
              <ul className="sppUnplaced">
                {plan.unplaced.map(u => <li key={u.story.id}><StoryRow story={u.story} project={project} note={u.reason} /></li>)}
              </ul>
              {plan.unplaced_total > plan.unplaced.length && <p className="sppMuted">Showing the first {plan.unplaced.length} of {plan.unplaced_total}.</p>}
            </section>
          )}

          {plan.outside_plan.length > 0 && (
            <section className="sppCard" data-testid="spp-outside">
              <div className="sppCardHead"><div><h3>Open stories of people who are not in this plan ({plan.outside_plan.length})</h3><p>Not counted for anyone.</p></div></div>
              <ul>{plan.outside_plan.map(s => <StoryRow key={s.id} story={s} project={project} note={s.assigned_to} />)}</ul>
            </section>
          )}

          <p className="sppFoot" data-testid="spp-foot">Made {plan.generated_at.replace('T', ' ').replace('Z', ' UTC')}. Shown here only: nothing was changed in Azure DevOps.</p>
        </div>
      )}
    </div>
  )
}
