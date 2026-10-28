import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SprintPlanningPage } from '../../components/SprintPlanningPage'
import { api } from '../../services/api'
import type { PlanSprint, SprintPlan, SprintPlanningSetup } from '../../types/api'
import { velocityContext } from './planningFixtures'

vi.mock('../../services/api', () => ({
  api: {
    teams: vi.fn(),
    sprintPlanningSetup: vi.fn(),
    sprintVelocityContext: vi.fn(),
    sprintPlan: vi.fn(),
    sprintCommit: vi.fn(),
  },
}))

const sprint = (id: string, project = 'Project A'): PlanSprint => ({
  id, name: `Sprint ${id.slice(1)}`, path: `${project}\\Sprint ${id.slice(1)}`, time_frame: 'future',
})

const setup = (project = 'Project A', team = 'Team A'): SprintPlanningSetup => ({
  team, sprints: ['s2', 's3', 's4'].map(id => sprint(id, project)), default_from_id: 's2', default_to_id: 's3',
  members: [{ name: 'Test Planner', unique_name: 'planner@example.test' }], areas: ['*'], work_item_types: ['User Story'],
  default_types: ['User Story'], per_person: 6, active_days: 10, notes: [],
})

const plan = (target = 's3', project = 'Project A', team = 'Team A'): SprintPlan => ({
  team, project, from_sprint: sprint('s2', project), to_sprint: sprint(target, project),
  per_person: 6, active_days: 10, work_item_types: ['User Story'], capacity_mode: 'points',
  people: [{
    name: 'Test Planner', unique_name: 'planner@example.test', areas: ['*'], capacity: 6,
    carried: [], already_planned: [], new: [{
      id: 101, title: 'Test story', type: 'User Story', state: 'New', state_category: 'proposed',
      area_path: project, iteration_path: project, assigned_to: '', assigned_unique: '', tags: [],
      points: 3, days_in_state: 0, state_since: null, state_since_exact: true, flags: [],
      url: 'https://example.test/story/101', comments: null, matched_area: '*',
    }], total: 1, open_places: 5, over_by: 0, warnings: [],
  }],
  flagged: [], unplaced: [], unplaced_total: 0, outside_plan: [], backlog_left: 0,
  summary: { people: 1, stories_planned: 1, carried: 0, new: 1, already_planned: 0, flagged: 0, blocked: 0, long_active: 0, unplaced: 0, open_places: 5 },
  notes: [], generated_at: '2026-10-25T12:00:00Z', posted_to_ado: false,
})

function deferred<Value>() {
  let resolve!: (value: Value) => void
  let reject!: (reason: Error) => void
  const promise = new Promise<Value>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

let container: HTMLDivElement
let root: Root
let currentProps: React.ComponentProps<typeof SprintPlanningPage>

function element<ElementType extends HTMLElement>(selector: string): ElementType {
  const found = container.querySelector<ElementType>(selector)
  if (!found) throw new Error(`Missing element: ${selector}`)
  return found
}

function button(text: string): HTMLButtonElement {
  const found = Array.from(container.querySelectorAll('button')).find(candidate => candidate.textContent?.includes(text))
  if (!found) throw new Error(`Missing button: ${text}`)
  return found
}

async function click(target: HTMLElement) {
  await act(async () => target.click())
}

async function select(selector: string, value: string) {
  await act(async () => {
    const control = element<HTMLSelectElement>(selector)
    control.value = value
    control.dispatchEvent(new Event('change', { bubbles: true }))
  })
}

async function enterNumber(selector: string, value: string) {
  await act(async () => {
    const control = element<HTMLInputElement>(selector)
    const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    setValue.call(control, value)
    control.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

async function render(overrides: Partial<typeof currentProps> = {}) {
  currentProps = { ...currentProps, ...overrides }
  await act(async () => root.render(<SprintPlanningPage {...currentProps} />))
}

async function changeContext(context: string) {
  if (context === 'team') await select('[data-testid="spp-team"]', 'Team B')
  else if (context === 'project') await render({ project: 'Project B' })
  else await render({ organization: 'org-b' })
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  localStorage.clear()
  for (const organization of ['org-a', 'org-b']) {
    for (const project of ['project a', 'project b']) {
      localStorage.setItem(`ado_sprint_planning_team:${organization}:${project}`, 'Team A')
    }
  }
  vi.mocked(api.teams).mockResolvedValue([{ id: 'team-a', name: 'Team A' }, { id: 'team-b', name: 'Team B' }])
  vi.mocked(api.sprintPlanningSetup).mockImplementation(async (_organization, project, team) => setup(project, team))
  vi.mocked(api.sprintVelocityContext).mockImplementation(async (_org, _project, _team, target) => velocityContext(target))
  vi.mocked(api.sprintPlan).mockImplementation(async request => plan(request.to_iteration_id, request.project, request.team))
  vi.mocked(api.sprintCommit).mockResolvedValue({ success: true, updated_count: 1, message: 'Test commit complete', errors: [] })
  currentProps = {
    organization: 'org-a', project: 'Project A', pat: 'test-token',
    projects: [{ id: 'project-a', name: 'Project A' }, { id: 'project-b', name: 'Project B' }],
  }
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  localStorage.clear()
  vi.unstubAllGlobals()
})

describe('sprint planning draft scope', () => {
  it('shows known sprint working days even when no member capacity is configured', async () => {
    const context = velocityContext()
    context.upcoming_capacity!.working_days = 21
    context.upcoming_capacity!.members = []
    vi.mocked(api.sprintVelocityContext).mockResolvedValue(context)
    await render()
    expect(element('[data-testid="spp-days-planner@example.test"]').textContent).toBe('21')
    expect(element('[data-testid="spp-pto-planner@example.test"]').textContent).toBe('Unavailable')
    expect(element('[data-testid="spp-hours-planner@example.test"]').textContent).toBe('Unavailable')
  })

  it.each([{ areas: [] }, { areas: ['Project A\\Legacy Area'] }])('plans any team-scoped area regardless of saved personal areas $areas', async ({ areas }) => {
    localStorage.setItem('ado_sprint_planning:org-a:project a:team a', JSON.stringify([{
      name: 'Test Planner', unique_name: 'planner@example.test', areas, included: true, manual: false,
      working_days: 7, pto_days: 2,
    }]))
    const actual = await vi.importActual<typeof import('../../services/api')>('../../services/api')
    const fetchPlan = vi.fn(async (_url: RequestInfo | URL, _options?: RequestInit) =>
      new Response(JSON.stringify(plan()), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchPlan)
    vi.mocked(api.sprintPlan).mockImplementation(actual.api.sprintPlan)
    await render()

    const capacity = element('[data-testid="spp-people"]')
    expect(capacity.querySelector('.sppPicker')).toBeNull()
    expect(capacity.querySelector('[data-testid^="spp-areas-"]')).toBeNull()
    expect(capacity.querySelectorAll('th')).toHaveLength(6)
    expect(capacity.textContent).not.toContain('Areas of choice')
    expect(element('[data-testid="spp-days-planner@example.test"]').textContent).toBe('10')
    expect(element('[data-testid="spp-pto-planner@example.test"]').textContent).toBe('0')
    expect(capacity.querySelector('input[type="number"]')).toBeNull()
    expect(element<HTMLButtonElement>('[data-testid="spp-plan"]').disabled).toBe(false)
    await click(element('[data-testid="spp-plan"]'))

    const request = JSON.parse(String(fetchPlan.mock.calls[0][1]?.body))
    expect(request.people).toEqual([expect.objectContaining({
      unique_name: 'planner@example.test', areas: ['*'], working_days: 10, pto_days: 0,
    })])
    expect(request).not.toHaveProperty('area_filter')
    expect(request.team).toBe('Team A')
  })

  it('removes optional filter controls and sends no backlog restrictions while keeping setup default types', async () => {
    vi.mocked(api.sprintPlanningSetup).mockResolvedValue({
      ...setup(), work_item_types: ['User Story', 'Bug', 'Product Backlog Item'], default_types: ['Product Backlog Item', 'Bug'],
    })
    const actual = await vi.importActual<typeof import('../../services/api')>('../../services/api')
    const fetchPlan = vi.fn(async (_url: RequestInfo | URL, _options?: RequestInit) =>
      new Response(JSON.stringify(plan()), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchPlan)
    vi.mocked(api.sprintPlan).mockImplementation(actual.api.sprintPlan)
    await render()

    const settings = element('[data-testid="spp-settings"]')
    expect(settings.querySelectorAll('input, select')).toHaveLength(3)
    expect(settings.textContent).not.toMatch(/Backlog Tags|Backlog Area|Work item types/i)
    expect(container.querySelector('[data-testid="spp-tags-filter"]')).toBeNull()
    expect(container.querySelector('[data-testid="spp-area-filter"]')).toBeNull()
    expect(container.querySelector('.sppTypes')).toBeNull()
    await click(element('[data-testid="spp-plan"]'))

    expect(fetchPlan).toHaveBeenCalledTimes(1)
    const request = JSON.parse(String(fetchPlan.mock.calls[0][1]?.body))
    expect(request).not.toHaveProperty('tags')
    expect(request).not.toHaveProperty('area_filter')
    expect(request.work_item_types).toEqual(['Product Backlog Item', 'Bug'])
    expect(request.per_person).toBe(6)
    expect(request.active_days).toBe(10)
  })

  it.each([0, 4, 10])('uses Capacity-tab working days %s without independent editable defaults', async (expected) => {
    const context = velocityContext()
    context.upcoming_capacity!.working_days = expected
    vi.mocked(api.sprintVelocityContext).mockResolvedValue(context)
    const actual = await vi.importActual<typeof import('../../services/api')>('../../services/api')
    const fetchPlan = vi.fn(async (_url: RequestInfo | URL, _options?: RequestInit) =>
      new Response(JSON.stringify(plan()), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchPlan)
    vi.mocked(api.sprintPlan).mockImplementation(actual.api.sprintPlan)
    await render()
    expect(element('[data-testid="spp-days-planner@example.test"]').textContent).toBe(String(expected))
    await click(element('[data-testid="spp-plan"]'))

    expect(fetchPlan).toHaveBeenCalledTimes(1)
    const request = JSON.parse(String(fetchPlan.mock.calls[0][1]?.body))
    expect(request.people[0].working_days).toBe(expected)
    expect(request.velocity_capacity.target_iteration_id).toBe('s3')
    expect(request.capacity_mode).toBe('points')
  })

  it('uses shared scoped Capacity overrides and invalidates the plan when Capacity changes', async () => {
    localStorage.setItem('ado_sprint_capacity:v2:org-a:project a:team-a:s3', JSON.stringify([{
      id: 'planner', name: 'Test Planner', unique_name: 'planner@example.test', capacity_per_day: 6, days_off: 2, activity: 'Development',
    }]))
    await render()
    expect(element('[data-testid="spp-pto-planner@example.test"]').textContent).toBe('2')
    expect(element('[data-testid="spp-hours-planner@example.test"]').textContent).toBe('48')
    await click(element('[data-testid="spp-plan"]'))
    expect(vi.mocked(api.sprintPlan).mock.calls[0][0].velocity_capacity?.upcoming_members).toContainEqual(expect.objectContaining({ days_off: 2, capacity_per_day: 6 }))
    await act(async () => window.dispatchEvent(new Event('sprint-capacity-changed')))
    expect(container.querySelector('[data-testid="spp-result"]')).toBeNull()
  })

  it('reports capacity read errors and rejects obsolete capacity responses after a sprint switch', async () => {
    const pending = deferred<ReturnType<typeof velocityContext>>()
    vi.mocked(api.sprintVelocityContext).mockReturnValueOnce(pending.promise).mockRejectedValueOnce(new Error('Unavailable'))
    await render()
    expect(element<HTMLButtonElement>('[data-testid="spp-plan"]').disabled).toBe(true)
    await select('[data-testid="spp-to"]', 's4')
    await act(async () => pending.resolve(velocityContext()))
    expect(container.textContent).toContain('Capacity data could not be loaded: Unavailable')
    expect(container.querySelector('[data-testid="spp-velocity-baseline"]')).toBeNull()
    expect(element<HTMLButtonElement>('[data-testid="spp-plan"]').disabled).toBe(true)
  })

  it('shows a zero-point budget and existing overload without falling back to story count', async () => {
    const generated = plan()
    const person = generated.people[0]
    person.carried = person.new
    person.new = []
    person.points_capacity = 0
    person.points_planned = 3
    person.points_over_by = 3
    vi.mocked(api.sprintPlan).mockResolvedValueOnce(generated)
    await render()
    await click(element('[data-testid="spp-plan"]'))

    expect(element('[data-testid="spp-count-planner@example.test"]').textContent).toBe('3 of 0 pts')
    expect(element('[data-testid="spp-card-planner@example.test"]').classList.contains('over')).toBe(true)
  })

  it('invalidates a reviewed plan and its open confirmation when the sprint changes', async () => {
    await render()
    await click(element('[data-testid="spp-plan"]'))
    await click(button('Commit to Azure DevOps'))
    const obsoleteConfirmation = button('Confirm & Commit')

    await select('[data-testid="spp-to"]', 's4')
    await click(obsoleteConfirmation)

    expect(api.sprintCommit).not.toHaveBeenCalled()
    expect(container.querySelector('[data-testid="spp-result"]')).toBeNull()
    expect(container.textContent).not.toContain('Commit Sprint Plan to Azure DevOps')
    expect(container.textContent).not.toContain('Commit to Azure DevOps')
  })

  it('discards a late response from the previously selected sprint', async () => {
    const pending = deferred<SprintPlan>()
    vi.mocked(api.sprintPlan).mockReturnValueOnce(pending.promise)
    await render()
    await click(element('[data-testid="spp-plan"]'))
    await select('[data-testid="spp-to"]', 's4')
    await act(async () => pending.resolve(plan('s3')))

    expect(container.querySelector('[data-testid="spp-result"]')).toBeNull()
    expect(container.textContent).not.toContain('Commit to Azure DevOps')
    expect(element<HTMLButtonElement>('[data-testid="spp-plan"]').disabled).toBe(false)
    expect(api.sprintCommit).not.toHaveBeenCalled()
  })

  it('does not revive an old request after returning to its original sprint', async () => {
    const pending = deferred<SprintPlan>()
    vi.mocked(api.sprintPlan).mockReturnValueOnce(pending.promise)
    await render()
    await click(element('[data-testid="spp-plan"]'))
    await select('[data-testid="spp-to"]', 's4')
    await select('[data-testid="spp-to"]', 's3')
    await act(async () => pending.resolve(plan('s3')))

    expect(container.querySelector('[data-testid="spp-result"]')).toBeNull()
    await click(element('[data-testid="spp-plan"]'))
    expect(container.querySelector('[data-testid="spp-result"]')).not.toBeNull()
    expect(api.sprintPlan).toHaveBeenCalledTimes(2)
  })

  it.each(['organization', 'project', 'team'])('invalidates a reviewed draft after the %s changes', async context => {
    await render()
    await click(element('[data-testid="spp-plan"]'))
    await click(button('Commit to Azure DevOps'))
    await changeContext(context)

    expect(container.querySelector('[data-testid="spp-result"]')).toBeNull()
    expect(container.textContent).not.toContain('Commit Sprint Plan to Azure DevOps')
    expect(container.textContent).not.toContain('Commit to Azure DevOps')
    expect(api.sprintCommit).not.toHaveBeenCalled()
  })

  it.each(['organization', 'project', 'team'])('discards a late response after the %s changes', async context => {
    const pending = deferred<SprintPlan>()
    vi.mocked(api.sprintPlan).mockReturnValueOnce(pending.promise)
    await render()
    await click(element('[data-testid="spp-plan"]'))
    await changeContext(context)
    await act(async () => pending.resolve(plan()))

    expect(container.querySelector('[data-testid="spp-result"]')).toBeNull()
    expect(container.textContent).not.toContain('Commit to Azure DevOps')
    expect(api.sprintCommit).not.toHaveBeenCalled()
  })

  it('keeps a newer request pending when an obsolete request finishes', async () => {
    const oldRequest = deferred<SprintPlan>()
    const newRequest = deferred<SprintPlan>()
    vi.mocked(api.sprintPlan).mockReturnValueOnce(oldRequest.promise).mockReturnValueOnce(newRequest.promise)
    await render()
    await click(element('[data-testid="spp-plan"]'))
    await select('[data-testid="spp-to"]', 's4')
    await click(element('[data-testid="spp-plan"]'))
    await act(async () => oldRequest.resolve(plan('s3')))

    expect(container.querySelector('[data-testid="spp-result"]')).toBeNull()
    expect(element<HTMLButtonElement>('[data-testid="spp-plan"]').disabled).toBe(true)
    await act(async () => newRequest.resolve(plan('s4')))
    expect(container.textContent).toContain('Team Workload Swimlanes for Sprint 4')
    expect(element<HTMLButtonElement>('[data-testid="spp-plan"]').disabled).toBe(false)
  })

  it('ignores errors from an obsolete request', async () => {
    const pending = deferred<SprintPlan>()
    vi.mocked(api.sprintPlan).mockReturnValueOnce(pending.promise)
    await render()
    await click(element('[data-testid="spp-plan"]'))
    await select('[data-testid="spp-to"]', 's4')
    await act(async () => pending.reject(new Error('Obsolete planning error')))

    expect(container.querySelector('[data-testid="spp-error"]')).toBeNull()
    expect(element<HTMLButtonElement>('[data-testid="spp-plan"]').disabled).toBe(false)
  })

  it('rejects a returned plan for a different destination', async () => {
    vi.mocked(api.sprintPlan).mockResolvedValueOnce(plan('s4'))
    await render()
    await click(element('[data-testid="spp-plan"]'))

    expect(container.querySelector('[data-testid="spp-result"]')).toBeNull()
    expect(container.textContent).toContain('does not match the selected project, team and sprint')
    expect(api.sprintCommit).not.toHaveBeenCalled()
  })

  it('commits an unchanged draft to exactly its reviewed destination', async () => {
    const reviewed = plan()
    reviewed.to_sprint.path = 'Project A\\Reviewed Sprint 3'
    vi.mocked(api.sprintPlan).mockResolvedValueOnce(reviewed)
    await render()
    await click(element('[data-testid="spp-plan"]'))
    await click(button('Commit to Azure DevOps'))
    expect(container.textContent).toContain(reviewed.to_sprint.path)
    await click(button('Confirm & Commit'))

    expect(api.sprintCommit).toHaveBeenCalledExactlyOnceWith({
      organization: 'org-a', project: 'Project A', team: 'Team A', pat: 'test-token',
      to_iteration_id: reviewed.to_sprint.id, to_iteration_path: reviewed.to_sprint.path,
      assignments: [{ story_id: 101, assigned_to: 'planner@example.test' }], sprint_goal: undefined,
    })
    expect(container.textContent).toContain('Test commit complete')
  })
})
