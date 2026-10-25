import { afterEach, describe, expect, it, vi } from 'vitest'
import type { PlannedPerson, PlanStory, SprintPlan } from '../../types/api'
import {
  ANY_AREA, addPerson, areaLabel, commentDate, dayMonth, daysInState, flagText, fullness, loadPeople, mergeMembers, peopleForPlan, personKey, plural, planAsMarkdown, planProblems,
  removePerson, savePeople, setAreas, setIncluded, setPtoDays, setWorkingDays, sprintLabel, storyCount,
  type PlanningPerson,
} from '../../utils/sprintPlanning'

function fakeStorage(initial: Record<string, string> = {}, broken = false) {
  const data = { ...initial }
  const guard = () => { if (broken) throw new Error('storage is blocked') }
  return {
    data,
    getItem: (key: string) => { guard(); return key in data ? data[key] : null },
    setItem: (key: string, value: string) => { guard(); data[key] = value },
    removeItem: (key: string) => { guard(); delete data[key] },
  }
}

afterEach(() => vi.unstubAllGlobals())

const ava: PlanningPerson = { name: 'Ava Stone', unique_name: 'ava@example.test', areas: ['Demo\\Alpha\\Backend'], included: true, manual: false }
const ben: PlanningPerson = { name: 'Ben Ortiz', unique_name: 'ben@example.test', areas: [], included: true, manual: false }

const story = (over: Partial<PlanStory> = {}): PlanStory => ({
  id: 1, title: 'A story', type: 'User Story', state: 'Active', state_category: 'inprogress', area_path: 'Demo\\Alpha\\Backend', iteration_path: 'Demo\\Sprint 2', assigned_to: 'Ava Stone',
  assigned_unique: 'ava@example.test', tags: [], points: null, days_in_state: 3, state_since: '2026-10-05T12:00:00Z', state_since_exact: true, flags: [], url: 'https://x.test/1', comments: null, matched_area: null, ...over,
})

describe('who is in the plan', () => {
  it('identifies a person by email, or by name when there is none', () => {
    expect(personKey(ava)).toBe('ava@example.test')
    expect(personKey({ name: ' Dan Reyes ', unique_name: '' })).toBe('dan reyes')
  })

  it('puts the team members first, with the areas saved for them, and keeps the people added by hand', () => {
    const saved: PlanningPerson[] = [{ ...ava, areas: ['Demo\\Alpha\\Ops'], included: false }, { name: 'Guest Dev', unique_name: '', areas: ['*'], included: true, manual: true },
      { name: 'Left Team', unique_name: 'left@example.test', areas: ['x'], included: true, manual: false }]
    const merged = mergeMembers(saved, [{ name: 'Ben Ortiz', unique_name: 'ben@example.test' }, { name: 'Ava Stone', unique_name: 'AVA@example.test' }])
    expect(merged.map(p => p.name)).toEqual(['Ben Ortiz', 'Ava Stone', 'Guest Dev'])  // the member who left is gone; the one added by hand stays
    expect(merged[1]).toMatchObject({ areas: ['Demo\\Alpha\\Ops'], included: false, manual: false })
    expect(merged[0]).toMatchObject({ areas: [], included: true })
  })

  it('lists a member once however many times Azure DevOps names them', () => {
    expect(mergeMembers([], [{ name: 'Ava', unique_name: 'a@x.test' }, { name: 'Ava', unique_name: 'a@x.test' }, { name: '', unique_name: '' }])).toHaveLength(1)
  })

  it('adds someone by name or by email, once', () => {
    expect(addPerson([], 'Dan Reyes')).toEqual([{ name: 'Dan Reyes', unique_name: '', areas: [], included: true, manual: true }])
    expect(addPerson([], 'dan.reyes@example.test')[0]).toMatchObject({ name: 'Dan Reyes', unique_name: 'dan.reyes@example.test', manual: true })
    expect(addPerson([ava], 'ava@example.test')).toEqual([ava])
    expect(addPerson([ava], 'ava stone')).toEqual([ava])
    expect(addPerson([ava], '   ')).toEqual([ava])
  })

  it('removes only people who were added by hand', () => {
    const guest = addPerson([ava], 'Guest Dev')
    expect(removePerson(guest, 'guest dev').map(p => p.name)).toEqual(['Ava Stone'])
    expect(removePerson(guest, personKey(ava)).map(p => p.name)).toEqual(['Ava Stone', 'Guest Dev'])
  })

  it('changes the areas and the inclusion of one person only', () => {
    const changed = setAreas([ava, ben], personKey(ben), ['Demo\\Alpha\\Frontend', ' Demo\\Alpha\\Frontend ', '', ANY_AREA])
    expect(changed[1].areas).toEqual(['Demo\\Alpha\\Frontend', '*'])
    expect(changed[0]).toBe(ava)
    expect(setIncluded([ava, ben], personKey(ava), false).map(p => p.included)).toEqual([false, true])
  })

  it('sends only the people who are included', () => {
    expect(peopleForPlan(setIncluded([ava, ben], personKey(ben), false))).toEqual([{ name: 'Ava Stone', unique_name: 'ava@example.test', areas: ['Demo\\Alpha\\Backend'] }])
  })

  it('keeps intentional zero capacity and days through storage, member merge and request serialization', () => {
    vi.stubGlobal('localStorage', fakeStorage())
    const people = setPtoDays(setWorkingDays([{ ...ava, capacity_points: 0 }], personKey(ava), 0), personKey(ava), 0)
    savePeople('org', 'project', 'team', people)
    const merged = mergeMembers(loadPeople('org', 'project', 'team'), [{ name: ava.name, unique_name: ava.unique_name }])
    const payload = JSON.parse(JSON.stringify(peopleForPlan(merged)))
    expect(payload[0]).toMatchObject({ working_days: 0, pto_days: 0, capacity_points: 0 })
    expect(peopleForPlan([ava])[0].working_days).toBeUndefined()
    expect(peopleForPlan([ava])[0].capacity_points).toBeUndefined()
  })
})

describe('what stops a plan', () => {
  it('needs the sprint to plan and someone to plan for', () => {
    expect(planProblems([ava], 's3').blocking).toEqual([])
    expect(planProblems([ava], '').blocking[0]).toContain('Choose the sprint')
    expect(planProblems([ava], 's2', 's2').blocking[0]).toContain('different sprint')
    expect(planProblems([], 's3').blocking).toEqual(['Add at least one person to plan for.'])
    expect(planProblems(setIncluded([ava], personKey(ava), false), 's3').blocking).toEqual(['Add at least one person to plan for.'])
  })

  it('only warns about people with no area of choice', () => {
    expect(planProblems([ava, ben], 's3')).toEqual({ blocking: [], warnings: ['Ben Ortiz has no area of choice, so no new story can be given.'] })
    expect(planProblems([ben, { ...ben, name: 'Dan', unique_name: 'dan@x.test' }], 's3').warnings[0]).toBe('Ben Ortiz, Dan have no area of choice, so no new stories can be given.')
    expect(planProblems(setIncluded([ben], personKey(ben), false), 's3').warnings).toEqual([])
  })
})

describe('keeping each team\'s people in this browser', () => {
  it('saves and loads them per organization, project and team', () => {
    const storage = fakeStorage()
    vi.stubGlobal('localStorage', storage)
    savePeople('MyOrg', 'Demo', 'Alpha', [ava])
    expect(Object.keys(storage.data)).toEqual(['ado_sprint_planning:myorg:demo:alpha'])
    expect(loadPeople('myorg', 'DEMO', 'alpha')).toEqual([ava])
    expect(loadPeople('myorg', 'Demo', 'Beta')).toEqual([])
  })

  it('forgets a team that has no people any more', () => {
    const storage = fakeStorage()
    vi.stubGlobal('localStorage', storage)
    savePeople('o', 'p', 't', [ava])
    savePeople('o', 'p', 't', [])
    expect(storage.data).toEqual({})
  })

  it('ignores what it cannot read', () => {
    vi.stubGlobal('localStorage', fakeStorage({ 'ado_sprint_planning:o:p:t': '{not json' }))
    expect(loadPeople('o', 'p', 't')).toEqual([])
    vi.stubGlobal('localStorage', fakeStorage({ 'ado_sprint_planning:o:p:t': JSON.stringify([null, 5, { name: '' }, { name: 'Ok', areas: ['a', 3, ' b '], included: false }]) }))
    expect(loadPeople('o', 'p', 't')).toEqual([{ name: 'Ok', unique_name: '', areas: ['a', 'b'], included: false, manual: false }])
  })

  it('works without storage', () => {
    vi.stubGlobal('localStorage', fakeStorage({}, true))
    expect(loadPeople('o', 'p', 't')).toEqual([])
    expect(() => savePeople('o', 'p', 't', [ava])).not.toThrow()
  })
})

describe('words for the page', () => {
  it('names a sprint with when it is and when it runs', () => {
    expect(sprintLabel({ id: 's2', name: 'Sprint 2', path: 'x', start: '2026-09-21T00:00:00Z', finish: '2026-10-02T00:00:00Z', time_frame: 'current' })).toBe('Sprint 2 (current) · 21 Sep – 2 Oct')
    expect(sprintLabel({ id: 's3', name: 'Sprint 3', path: 'x', time_frame: 'future' })).toBe('Sprint 3')
    expect(sprintLabel({ id: 's1', name: 'Sprint 1', path: 'x', start: '2026-09-07T00:00:00Z', finish: '2026-09-18T00:00:00Z', time_frame: 'past' })).toBe('Sprint 1 (past) · 7 Sep – 18 Sep')
  })

  it('shows an area without its project', () => {
    expect(areaLabel('Demo\\Alpha\\Backend', 'Demo')).toBe('Alpha\\Backend')
    expect(areaLabel('demo\\Alpha', ' DEMO ')).toBe('Alpha')
    expect(areaLabel('Demo', 'Demo')).toBe('Demo')
    expect(areaLabel('Other\\Alpha', 'Demo')).toBe('Other\\Alpha')
    expect(areaLabel(ANY_AREA, 'Demo')).toBe('Any area')
  })

  it('counts and pluralises', () => {
    expect(plural(1, 'story', 'stories')).toBe('1 story')
    expect(plural(2, 'story', 'stories')).toBe('2 stories')
    expect(plural(0, 'day')).toBe('0 days')
  })

  it('says how long a story has been in its state', () => {
    expect(daysInState(story({ days_in_state: 14 }))).toBe('14 days')
    expect(daysInState(story({ days_in_state: 1 }))).toBe('1 day')
    expect(daysInState(story({ days_in_state: 0 }))).toBe('today')
    expect(daysInState(story({ days_in_state: 12, state_since_exact: false }))).toBe('about 12 days')
    expect(daysInState(story({ days_in_state: null }))).toBe('')
  })

  it('formats dates the way the page shows them', () => {
    expect(dayMonth('2026-10-02T00:00:00Z')).toBe('2 Oct')
    expect(dayMonth(null)).toBe('')
    expect(commentDate('2026-10-07T10:00:00Z')).toBe('7 Oct 2026')
    expect(commentDate('nonsense')).toBe('')
  })

  it('names the flags', () => {
    expect(flagText({ code: 'blocked', reason: 'x' })).toBe('Blocked')
    expect(flagText({ code: 'active_too_long', reason: 'x' })).toBe('Active too long')
    expect(flagText({ code: 'other', reason: 'x' })).toBe('other')
  })
})

describe('the plan as text', () => {
  const person = (over: Partial<PlannedPerson> = {}): PlannedPerson => ({
    name: 'Ava Stone', unique_name: 'ava@example.test', areas: ['Demo\\Alpha\\Backend'], capacity: 6, carried: [story({ id: 10, title: 'Slow export', flags: [{ code: 'active_too_long', reason: 'In "Active" for 14 days (more than 10)' }] })],
    already_planned: [], new: [story({ id: 30, title: 'Backend one', state: 'New', assigned_to: '' })], total: 2, open_places: 4, over_by: 0, warnings: ['4 places still empty: no unassigned story is left in their areas.'], ...over,
  })
  const plan = (over: Partial<SprintPlan> = {}): SprintPlan => ({
    team: 'Alpha', project: 'Demo', from_sprint: { id: 's2', name: 'Sprint 2', path: 'x', time_frame: 'current' }, to_sprint: { id: 's3', name: 'Sprint 3', path: 'y', time_frame: 'future' },
    per_person: 6, active_days: 10, work_item_types: ['User Story'], people: [person()], unplaced: [{ story: story({ id: 33, title: 'Ops one' }), reason: 'nobody has chosen this area' }], unplaced_total: 1,
    flagged: [story({ id: 10, title: 'Slow export', flags: [{ code: 'active_too_long', reason: 'In "Active" for 14 days (more than 10)' }],
      comments: [{ author: 'Ava Stone', date: '2026-10-01T09:00:00Z', text: 'Waiting for\nthe vendor' }] })],
    outside_plan: [], backlog_left: 0, summary: { people: 1, stories_planned: 2, carried: 1, new: 1, already_planned: 0, flagged: 1, blocked: 0, long_active: 1, unplaced: 1, open_places: 4 },
    notes: [], generated_at: '2026-10-08T12:00:00Z', posted_to_ado: false, ...over,
  })

  it('has the flagged stories with their comments first, then each person, then what was not placed', () => {
    const text = planAsMarkdown(plan())
    expect(text.startsWith('# Sprint plan: Sprint 3\n')).toBe(true)
    expect(text).toContain('Nothing was changed in Azure DevOps.')
    expect(text.indexOf('## Needs a look first')).toBeLessThan(text.indexOf('## Ava Stone (2 of 6)'))
    expect(text).toContain('> **Ava Stone** (1 Oct 2026): Waiting for the vendor')
    expect(text).toContain('- #10 Slow export (Active; In "Active" for 14 days (more than 10))')
    expect(text).toContain('New:\n- #30 Backend one (New)')
    expect(text).toContain('_4 places still empty: no unassigned story is left in their areas._')
    expect(text).toContain('## Not placed (1)\n- #33 Ops one: nobody has chosen this area')
  })

  it('says when comments are missing or could not be read', () => {
    const base = plan().flagged[0]
    expect(planAsMarkdown(plan({ flagged: [{ ...base, comments: [] }] }))).toContain('_No comments._')
    expect(planAsMarkdown(plan({ flagged: [{ ...base, comments: null }] }))).toContain('_The comments could not be read._')
  })

  it('leaves out the sections that are empty', () => {
    const text = planAsMarkdown(plan({ flagged: [], unplaced: [], unplaced_total: 0, people: [person({ carried: [], new: [], warnings: [], total: 0 })] }))
    expect(text).not.toContain('Needs a look first')
    expect(text).not.toContain('Not placed')
    expect(text).not.toContain('Carried over:')
  })

  it('counts a person\'s stories and how full their sprint is', () => {
    expect(storyCount(person())).toBe(2)
    expect(fullness(person())).toBe('2 of 6')
  })
})
