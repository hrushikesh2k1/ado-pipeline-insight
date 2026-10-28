import type { AdoCapacityMember, CapacitySnapshot, PlanPerson, VelocityCapacity, VelocityContext } from '../types/api'

export const capacityStorageKey = (org: string, project: string, team: string, iteration: string) =>
  `ado_sprint_capacity:v2:${[org, project, team, iteration].map(value => value.trim().toLowerCase()).join(':')}`

export function loadCapacityMembers(org: string, project: string, team: string, iteration: string): AdoCapacityMember[] {
  const key = capacityStorageKey(org, project, team, iteration)
  const raw = localStorage.getItem(key) ?? localStorage.getItem(`ado_sprint_capacity_${team || 'default'}_${iteration || 'current'}`)
  if (!raw) return []
  const parsed: unknown = JSON.parse(raw)
  if (!Array.isArray(parsed) || parsed.some(member => !member || typeof member !== 'object'
    || typeof member.name !== 'string' || typeof member.id !== 'string'
    || !Number.isFinite(member.capacity_per_day) || member.capacity_per_day < 0
    || !Number.isFinite(member.days_off) || member.days_off < 0)) {
    throw new Error('Saved Capacity tab settings are invalid. Review capacity settings for this team and sprint.')
  }
  return parsed
}

export function mergeCapacityMembers(ado: AdoCapacityMember[], saved: AdoCapacityMember[]): AdoCapacityMember[] {
  const members: AdoCapacityMember[] = ado.map(member => ({ ...member, source: member.source || 'ado' }))
  saved.forEach(member => {
    const old = members.find(candidate => candidate.id === member.id)
      ?? capacityForPerson({ iteration_id: '', working_days: 0, members }, { name: member.name, unique_name: member.unique_name || '' })
    const merged = { ...old, ...member, id: old?.id || member.id,
      unique_name: old?.unique_name || member.unique_name, name: old?.name || member.name,
      source: member.source || old?.source || 'manual' }
    if (old) members[members.indexOf(old)] = merged
    else members.push(merged)
  })
  return members.sort((a, b) => a.name.localeCompare(b.name))
}

export const availableCapacityDays = (workingDays: number, daysOff: number) => Math.max(0, workingDays - daysOff)
export function sprintWorkingDays(supplied?: number | null, start?: string | null, finish?: string | null): number | null {
  if (supplied != null) return supplied
  if (!start || !finish) return null
  const first = new Date(start), last = new Date(finish)
  if (!Number.isFinite(first.getTime()) || !Number.isFinite(last.getTime())) return null
  const current = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), first.getUTCDate()))
  const end = Date.UTC(last.getUTCFullYear(), last.getUTCMonth(), last.getUTCDate())
  let days = 0
  while (current.getTime() <= end) {
    if (current.getUTCDay() !== 0 && current.getUTCDay() !== 6) days++
    current.setUTCDate(current.getUTCDate() + 1)
  }
  return days
}
export const totalCapacityHours = (workingDays: number, member: AdoCapacityMember) =>
  Math.round(availableCapacityDays(workingDays, member.days_off) * member.capacity_per_day * 10) / 10

export function withSavedCapacity(context: VelocityContext, org: string, project: string, teamId: string): VelocityContext {
  const overlay = (snapshot: CapacitySnapshot | null): CapacitySnapshot | null => snapshot ? {
    ...snapshot, members: mergeCapacityMembers(snapshot.members, loadCapacityMembers(org, project, teamId, snapshot.iteration_id)),
  } : null
  return { ...context, upcoming_capacity: overlay(context.upcoming_capacity), previous_capacity: overlay(context.previous_capacity) }
}

export function velocityCapacityInput(context: VelocityContext): VelocityCapacity {
  const members = (snapshot: CapacitySnapshot | null) => (snapshot?.members ?? []).map(member => ({
    name: member.name, unique_name: member.unique_name || '', capacity_per_day: member.capacity_per_day, days_off: member.days_off,
  }))
  return { target_iteration_id: context.target.id, previous_iteration_id: context.previous?.id ?? null,
    upcoming_members: members(context.upcoming_capacity), previous_members: members(context.previous_capacity) }
}

export function capacityForPerson(snapshot: CapacitySnapshot | null, person: Pick<PlanPerson, 'name' | 'unique_name'>): AdoCapacityMember | null {
  if (!snapshot) return null
  const normalize = (value: string) => value.trim().toLowerCase()
  const unique = normalize(person.unique_name)
  const identities = unique ? snapshot.members.filter(member => normalize(member.unique_name || '') === unique) : []
  if (identities.length) return identities.length === 1 ? identities[0] : null
  const names = snapshot.members.filter(member => normalize(member.name) === normalize(person.name)
    && (!unique || !member.unique_name))
  return names.length === 1 ? names[0] : null
}
