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
      const { name, unique_name: unique, areas, included, manual } = p as Record<string, unknown>
      if (typeof name !== 'string' || !name.trim()) return []
      return [{ name: name.trim(), unique_name: typeof unique === 'string' ? unique.trim() : '', areas: cleanAreas(areas), included: included !== false, manual: manual === true }]
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
    merged.push({ name: member.name || member.unique_name, unique_name: member.unique_name, areas: old?.areas ?? [], included: old?.included ?? true, manual: false })
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

/** The people the plan is made for. */
export const peopleForPlan = (people: PlanningPerson[]): PlanPerson[] =>
  people.filter(p => p.included).map(p => ({ name: p.name, unique_name: p.unique_name, areas: p.areas }))

/** What stops a plan being made (the button stays off), and what is only worth a warning. */
export function planProblems(people: PlanningPerson[], fromId: string, toId: string): { blocking: string[]; warnings: string[] } {
  const chosen = people.filter(p => p.included)
  const blocking: string[] = []
  if (!fromId || !toId) blocking.push('Choose the sprint to carry stories from and the sprint to plan.')
  else if (fromId === toId) blocking.push('The sprint to plan must be a different sprint than the one stories are carried from.')
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
