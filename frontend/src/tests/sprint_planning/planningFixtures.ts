import type { PlanStory, PlannedPerson, SprintPlan, VelocityContext } from '../../types/api'
export const velocityContext = (target = 's3'): VelocityContext => ({
  target: { id: target, name: `Sprint ${target}`, path: `Demo\\Sprint ${target}`, time_frame: 'future' },
  previous: { id: 's1', name: 'Previous completed sprint', path: 'Demo\\Sprint 1', time_frame: 'past' },
  upcoming_capacity: { iteration_id: target, working_days: 10, members: [
    { id: 'ava', name: 'Ava', unique_name: 'ava@test', activity: 'Development', capacity_per_day: 8, days_off: 0 },
    { id: 'ben', name: 'Ben', unique_name: 'ben@test', activity: 'Development', capacity_per_day: 8, days_off: 0 },
    { id: 'planner', name: 'Test Planner', unique_name: 'planner@example.test', activity: 'Development', capacity_per_day: 8, days_off: 0 },
  ] },
  previous_capacity: { iteration_id: 's1', working_days: 10, members: [] },
  notes: [],
})
export const story = (over: Partial<PlanStory> = {}): PlanStory => ({
  id: 1, title: 'Blocked carryover', type: 'User Story', state: 'Active', state_category: 'inprogress', area_path: 'Demo\\Alpha',
  iteration_path: 'Demo\\Sprint 2', assigned_to: 'Ava', assigned_unique: 'ava@test', tags: [], points: 3, days_in_state: 15,
  state_since: null, state_since_exact: true, flags: [{ code: 'blocked', reason: 'Blocked' }], url: 'https://example.test/1', comments: [], matched_area: null, ...over,
})
export const person = (over: Partial<PlannedPerson> = {}): PlannedPerson => ({
  name: 'Ava', unique_name: 'ava@test', areas: ['*'], capacity: 6, points_capacity: 8, carried: [story()], already_planned: [], new: [],
  total: 1, open_places: 5, over_by: 0, warnings: [], ...over,
})
export const fixture = (): SprintPlan => ({
  team: 'Alpha', project: 'Demo', from_sprint: { id: 's2', name: 'Sprint 2', path: 'Demo\\Sprint 2', time_frame: 'current' },
  to_sprint: { id: 's3', name: 'Sprint 3', path: 'Demo\\Sprint 3', time_frame: 'future' },
  per_person: 6, active_days: 10, capacity_mode: 'points', work_item_types: ['User Story'], people: [person(), person({ name: 'Ben', unique_name: 'ben@test', carried: [], total: 0 })],
  flagged: [story()], unplaced: [{ story: story({ id: 2, title: 'Unplaced', iteration_path: 'Demo', flags: [], assigned_to: '', assigned_unique: '' }), reason: 'No area' }],
  unplaced_total: 1, outside_plan: [], backlog_left: 0, summary: { people: 2, stories_planned: 1, carried: 1, new: 0, already_planned: 0, flagged: 1, blocked: 1, long_active: 0, unplaced: 1, open_places: 11 },
  notes: [], generated_at: '2026-10-16T00:00:00Z', posted_to_ado: false,
})
