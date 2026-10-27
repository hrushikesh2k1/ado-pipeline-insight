import type { PlanPerson, PlanSprint, PlanStory, PlannedPerson, SprintPlan, StoryFlag, TeamMemberChoice } from '../types/api'

/** An area of choice that means "any area". */
export const ANY_AREA = '*'
export const DEFAULT_PER_PERSON = 6
export const DEFAULT_ACTIVE_DAYS = 10
export const MIN_PER_PERSON = 1
export const MAX_PER_PERSON = 30

/** A person on the planning page: who they are, the areas they chose, and whether they are in this plan. */
export type PlanningPerson = PlanPerson & { included: boolean; manual: boolean }

export const personKey = (p: Pick<PlanPerson, 'name' | 'unique_name'>): string => (p.unique_name || p.name).trim().toLowerCase()

const storageKey = (org: string, project: string, team: string) => `ado_sprint_planning:${[org, project, team].map(s => s.trim().toLowerCase()).join(':')}`

const cleanAreas = (value: unknown): string[] =>
  Array.isArray(value) ? [...new Set(value.filter((a): a is string => typeof a === 'string').map(a => a.trim()).filter(Boolean))] : []

/** The people saved for a team in this browser (their areas of choice), or none. Anything unreadable is ignored. */
export function loadPeople(org: string, project: string, team: string): PlanningPerson[] {
  try {
    const raw = localStorage.getItem(storageKey(org, project, team))
    const parsed: unknown = raw ? JSON.parse(raw) : null
    if (!Array.isArray(parsed)) return []
    return parsed.flatMap((p): PlanningPerson[] => {
      if (!p || typeof p !== 'object') return []
      const { name, unique_name: unique, areas, included, manual, working_days, pto_days, focus_factor, capacity_points } = p as Record<string, unknown>
      if (typeof name !== 'string' || !name.trim()) return []
      const item: PlanningPerson = {
        name: name.trim(),
        unique_name: typeof unique === 'string' ? unique.trim() : '',
        areas: cleanAreas(areas),
        included: included !== false,
        manual: manual === true,
      }
      if (typeof working_days === 'number') item.working_days = working_days
      if (typeof pto_days === 'number') item.pto_days = pto_days
      if (typeof focus_factor === 'number') item.focus_factor = focus_factor
      if (typeof capacity_points === 'number') item.capacity_points = capacity_points
      return [item]
    })
  } catch {
    return []
  }
}

export function savePeople(org: string, project: string, team: string, people: PlanningPerson[]): void {
  try {
    if (people.length) localStorage.setItem(storageKey(org, project, team), JSON.stringify(people))
    else localStorage.removeItem(storageKey(org, project, team))
  } catch { /* storage blocked: the choices stay on the page for this visit */ }
}

/** The team's members first, with the areas saved for them; then the people added by hand. A saved person who is no longer a member and was not added by hand is dropped. */
export function mergeMembers(saved: PlanningPerson[], members: TeamMemberChoice[]): PlanningPerson[] {
  const byKey = new Map(saved.map(p => [personKey(p), p]))
  const merged: PlanningPerson[] = []
  const seen = new Set<string>()
  for (const member of members) {
    const key = personKey(member)
    if (!key || seen.has(key)) continue
    seen.add(key)
    const old = byKey.get(key)
    const p: PlanningPerson = {
      name: member.name || member.unique_name,
      unique_name: member.unique_name,
      areas: old?.areas ?? [],
      included: old?.included ?? true,
      manual: false,
    }
    if (old?.working_days !== undefined) p.working_days = old.working_days
    if (old?.pto_days !== undefined) p.pto_days = old.pto_days
    if (old?.focus_factor !== undefined) p.focus_factor = old.focus_factor
    if (old?.capacity_points !== undefined) p.capacity_points = old.capacity_points
    merged.push(p)
  }
  for (const p of saved) {
    if (p.manual && !seen.has(personKey(p))) {
      seen.add(personKey(p))
      merged.push(p)
    }
  }
  return merged
}

/** Someone added by hand: a name, or an email (then the email also identifies them in Azure DevOps). */
export function addPerson(people: PlanningPerson[], text: string): PlanningPerson[] {
  const value = text.trim()
  if (!value) return people
  const person: PlanningPerson = value.includes('@')
    ? { name: value.split('@')[0].replace(/[._]+/g, ' ').replace(/\b\w/g, c => c.toUpperCase()), unique_name: value, areas: [], included: true, manual: true }
    : { name: value, unique_name: '', areas: [], included: true, manual: true }
  return people.some(p => personKey(p) === personKey(person) || p.name.toLowerCase() === person.name.toLowerCase()) ? people : [...people, person]
}

export const removePerson = (people: PlanningPerson[], key: string): PlanningPerson[] => people.filter(p => personKey(p) !== key || !p.manual)

export const setAreas = (people: PlanningPerson[], key: string, areas: string[]): PlanningPerson[] =>
  people.map(p => (personKey(p) === key ? { ...p, areas: cleanAreas(areas) } : p))

export const setIncluded = (people: PlanningPerson[], key: string, included: boolean): PlanningPerson[] =>
  people.map(p => (personKey(p) === key ? { ...p, included } : p))

export const setPtoDays = (people: PlanningPerson[], key: string, pto: number): PlanningPerson[] =>
  people.map(p => (personKey(p) === key ? { ...p, pto_days: Math.max(0, pto) } : p))

export const setWorkingDays = (people: PlanningPerson[], key: string, days: number): PlanningPerson[] =>
  people.map(p => (personKey(p) === key ? { ...p, working_days: Math.max(0, days) } : p))

/** The people the plan is made for. */
export const peopleForPlan = (people: PlanningPerson[]): PlanPerson[] =>
  people.filter(p => p.included).map(p => {
    const res: PlanPerson = {
      name: p.name,
      unique_name: p.unique_name,
      areas: p.areas,
    }
    if (p.working_days !== undefined) res.working_days = p.working_days
    if (p.pto_days !== undefined) res.pto_days = p.pto_days
    if (p.focus_factor !== undefined) res.focus_factor = p.focus_factor
    if (p.capacity_points !== undefined) res.capacity_points = p.capacity_points
    return res
  })

/** What stops a plan being made (the button stays off), and what is only worth a warning. */
export function planProblems(people: PlanningPerson[], toId: string, fromId?: string): { blocking: string[]; warnings: string[] } {
  const chosen = people.filter(p => p.included)
  const blocking: string[] = []
  if (!toId) blocking.push('Choose the sprint to plan.')
  else if (fromId && fromId === toId) blocking.push('The sprint to plan must be a different sprint than the one stories are carried from.')
  if (!chosen.length) blocking.push('Add at least one person to plan for.')
  const without = chosen.filter(p => !p.areas.length)
  const warnings = without.length
    ? [`${without.map(p => p.name).join(', ')} ${without.length === 1 ? 'has' : 'have'} no area of choice, so ${without.length === 1 ? 'no new story' : 'no new stories'} can be given.`]
    : []
  return { blocking, warnings }
}

// ---------------------------------------------------------------- showing things

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "21 Sep" from an ISO date (UTC, like Azure DevOps writes it); empty when there is none. */
export function dayMonth(iso?: string | null): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '')
  return match ? `${Number(match[3])} ${MONTHS[Number(match[2]) - 1]}` : ''
}

export function sprintLabel(s: PlanSprint): string {
  const when = s.start && s.finish ? ` · ${dayMonth(s.start)} – ${dayMonth(s.finish)}` : ''
  const frame = s.time_frame === 'current' ? ' (current)' : s.time_frame === 'past' ? ' (past)' : ''
  return `${s.name}${frame}${when}`
}

/** The area path without the project at its start: "Alpha\\Backend" for "Demo\\Alpha\\Backend". */
export function areaLabel(path: string, project = ''): string {
  if (path === ANY_AREA) return 'Any area'
  const parts = path.split('\\').filter(Boolean)
  return parts.length > 1 && parts[0].toLowerCase() === project.trim().toLowerCase() ? parts.slice(1).join('\\') : path
}

export const plural = (n: number, one: string, many = `${one}s`): string => `${n} ${n === 1 ? one : many}`

export function flagText(flag: StoryFlag): string {
  return flag.code === 'blocked' ? 'Blocked' : flag.code === 'active_too_long' ? 'Active too long' : flag.code
}

/** How full a person's sprint is: "3 of 6". */
export const fullness = (p: Pick<PlannedPerson, 'total' | 'capacity'>): string => `${p.total} of ${p.capacity}`

export const storyCount = (p: PlannedPerson): number => p.carried.length + p.already_planned.length + p.new.length

export function commentDate(iso?: string | null): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '')
  return match ? `${Number(match[3])} ${MONTHS[Number(match[2]) - 1]} ${match[1]}` : ''
}

/** The days a story has been in its state, as words: "14 days", "1 day", "since today"; empty when unknown. */
export function daysInState(story: Pick<PlanStory, 'days_in_state' | 'state_since_exact'>): string {
  if (story.days_in_state === null || story.days_in_state === undefined) return ''
  const days = story.days_in_state === 0 ? 'today' : plural(story.days_in_state, 'day')
  return story.state_since_exact ? days : `about ${days}`
}

/** The plan as Markdown, to paste into a chat or a meeting note. */
export function planAsMarkdown(plan: SprintPlan): string {
  const line = (s: PlanStory) => `- #${s.id} ${s.title} (${s.state}${s.flags.length ? `; ${s.flags.map(f => f.reason).join('; ')}` : ''})`
  const out: string[] = [`# Sprint plan: ${plan.to_sprint.name}`, '', `Team ${plan.team}. Stories carried over from ${plan.from_sprint.name}. ${plan.per_person} stories per person. Nothing was changed in Azure DevOps.`, '']
  if (plan.sprint_goal) {
    out.push(`> **Sprint Goal:** ${plan.sprint_goal}`, '')
  }
  if (plan.flagged.length) {
    out.push('## Needs a look first', '')
    for (const s of plan.flagged) {
      out.push(`### #${s.id} ${s.title}`, `${s.assigned_to || 'Nobody'} · ${s.state} · ${s.flags.map(f => f.reason).join('; ')}`)
      if (s.comments === null) out.push('_The comments could not be read._')
      else if (!s.comments.length) out.push('_No comments._')
      else s.comments.forEach(c => out.push(`> **${c.author}** (${commentDate(c.date)}): ${c.text.replace(/\s+/g, ' ')}`))
      out.push('')
    }
  }
  for (const p of plan.people) {
    out.push(`## ${p.name} (${fullness(p)})`)
    if (p.carried.length) out.push('Carried over:', ...p.carried.map(line))
    if (p.already_planned.length) out.push(`Already in ${plan.to_sprint.name}:`, ...p.already_planned.map(line))
    if (p.new.length) out.push('New:', ...p.new.map(line))
    p.warnings.forEach(w => out.push(`_${w}_`))
    out.push('')
  }
  if (plan.unplaced_total) out.push(`## Not placed (${plan.unplaced_total})`, ...plan.unplaced.map(u => `- #${u.story.id} ${u.story.title}: ${u.reason}`), '')
  return out.join('\n').trimEnd() + '\n'
}



/** Move a draft assignment atomically; no Azure DevOps write happens here. */
export function reassignStory(plan: SprintPlan, storyId: number, targetKey: string): SprintPlan {
  const target = targetKey ? plan.people.find(p => personKey(p) === targetKey) : undefined
  if (targetKey && !target) return plan
  const lanes = ['carried', 'already_planned', 'new'] as const
  let moving: PlanStory | undefined
  let lane: typeof lanes[number] = 'new'
  for (const p of plan.people) for (const l of lanes) {
    const match = p[l].find(s => s.id === storyId)
    if (match) {
      if (target && personKey(p) === personKey(target)) return plan
      moving = match; lane = l
    }
  }
  const fromUnplaced = plan.unplaced.find(u => u.story.id === storyId)
  if (!moving) {
    moving = fromUnplaced?.story
    if (!moving || !target) return plan
    lane = moving.iteration_path === plan.from_sprint.path ? 'carried'
      : moving.iteration_path === plan.to_sprint.path ? 'already_planned' : 'new'
  }
  const story = { ...moving, assigned_to: target?.name ?? '', assigned_unique: target?.unique_name ?? '', matched_area: null }
  const people = plan.people.map(p => {
    const row = { ...p, carried: p.carried.filter(s => s.id !== storyId), already_planned: p.already_planned.filter(s => s.id !== storyId), new: p.new.filter(s => s.id !== storyId) }
    if (target && personKey(p) === personKey(target)) row[lane] = [...row[lane], story]
    return row
  })
  const unplaced = plan.unplaced.filter(u => u.story.id !== storyId)
  if (!target) unplaced.push({ story, reason: 'Excluded manually from this draft; Azure DevOps is unchanged.' })
  const hiddenUnplaced = Math.max(0, plan.unplaced_total - plan.unplaced.length)
  return recalculatePlan({ ...plan, people, unplaced, unplaced_total: hiddenUnplaced + unplaced.length })
}

const points = (stories: PlanStory[]) => Math.round(stories.reduce((sum, s) => sum + (s.points ?? 0), 0) * 10) / 10

/** Refresh all derived draft metrics after a manual move, matching planner risk rules. */
export function recalculatePlan(plan: SprintPlan): SprintPlan {
  const people = plan.people.map(p => {
    const total = storyCount(p)
    const points_carried = points(p.carried), points_already_planned = points(p.already_planned), points_new = points(p.new)
    const points_planned = Math.round((points_carried + points_already_planned + points_new) * 10) / 10
    const cap = p.points_capacity ?? p.capacity_points ?? 0
    const open_places = Math.max(0, p.capacity - total), over_by = Math.max(0, total - p.capacity)
    const warnings: string[] = []
    if (!p.areas.length) warnings.push('No area of choice is set, so no new story can be given to this person.')
    if (open_places) warnings.push(`${open_places} places still empty in this draft.`)
    if (over_by) warnings.push(`${over_by} more than the ${p.capacity} planned.`)
    if (points_planned > cap * 1.15) warnings.push(`Capacity exceeded: ${points_planned} pts allocated exceeds estimated ${cap} pts capacity.`)
    return { ...p, total, open_places, over_by, points_carried, points_already_planned, points_new, points_planned,
      points_open: Math.max(0, Math.round((cap - points_planned) * 10) / 10),
      points_over_by: Math.max(0, Math.round((points_planned - cap) * 10) / 10), warnings }
  })
  const all = people.flatMap(p => [...p.carried, ...p.already_planned, ...p.new])
  const flagged = [...all.filter(s => s.flags.length && s.iteration_path === plan.from_sprint.path), ...plan.outside_plan.filter(s => s.flags.length)]
  const blocked = flagged.filter(s => s.flags.some(f => f.code === 'blocked')).length
  const long_active = flagged.filter(s => s.flags.some(f => f.code === 'active_too_long')).length
  const unpointed_stories = all.filter(s => s.points === null).length
  const overloaded = people.filter(p => (p.points_planned ?? 0) > (p.points_capacity ?? p.capacity_points ?? 0))
  const score = blocked * 2 + (unpointed_stories ? unpointed_stories < 3 ? 1 : 2 : 0) + (overloaded.length ? 2 : 0)
  const risk_reasons: string[] = [], ai_recommendations: string[] = []
  if (blocked) {
    risk_reasons.push(`${blocked} carried-over ${blocked === 1 ? 'story is' : 'stories are'} currently Blocked.`)
    ai_recommendations.push(`Unblock or descope ${blocked} blocked work items before confirming sprint commitment.`)
  }
  if (unpointed_stories) {
    risk_reasons.push(`${unpointed_stories} planned ${unpointed_stories === 1 ? 'story has' : 'stories have'} no Story Points estimated.`)
    ai_recommendations.push(`Estimate points for ${unpointed_stories} unpointed items to ensure accurate workload balancing.`)
  }
  if (overloaded.length) {
    const names = overloaded.map(p => p.name).join(', ')
    risk_reasons.push(`Capacity exceeded for ${names}.`)
    ai_recommendations.push(`Rebalance assignments from ${names} to team members with available capacity.`)
  } else if (people.some(p => p.open_places && p.areas.length)) ai_recommendations.push('All team members are within capacity limits. Review sprint goal alignment.')
  return { ...plan, people, flagged, ai_recommendations, summary: { ...plan.summary,
    people: people.length, stories_planned: all.length, carried: people.reduce((n, p) => n + p.carried.length, 0),
    already_planned: people.reduce((n, p) => n + p.already_planned.length, 0), new: people.reduce((n, p) => n + p.new.length, 0),
    flagged: flagged.length, blocked, long_active, unplaced: plan.unplaced_total, open_places: people.reduce((n, p) => n + p.open_places, 0),
    total_points_planned: points(all), total_points_capacity: Math.round(people.reduce((n, p) => n + (p.points_capacity ?? p.capacity_points ?? 0), 0) * 10) / 10,
    points_carried: points(people.flatMap(p => p.carried)), points_new: points(people.flatMap(p => p.new)), unpointed_stories,
    risk_score: score >= 4 ? 'High' : score >= 2 ? 'Medium' : 'Low', risk_reasons, sprint_confidence_pct: Math.max(40, Math.min(95, 95 - score * 12)),
  } }
}

/** Deduplicate exact assignments, rejecting conflicting owners before any write. */
export function commitAssignments(plan: SprintPlan): import('../types/api').StoryAssignment[] {
  const assignments = new Map<number, string>()
  for (const person of plan.people) for (const story of [...person.carried, ...person.already_planned, ...person.new]) {
    const owner = person.unique_name || person.name
    if (assignments.has(story.id) && assignments.get(story.id) !== owner) throw new Error(`Work item #${story.id} has conflicting planned owners. Generate the plan again.`)
    assignments.set(story.id, owner)
  }
  return [...assignments].map(([story_id, assigned_to]) => ({ story_id, assigned_to }))
}
