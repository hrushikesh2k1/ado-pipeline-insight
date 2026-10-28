import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SprintPlanningPage } from '../../components/SprintPlanningPage'
import { api } from '../../services/api'
import type { SprintPlanningSetup, SprintPlan } from '../../types/api'
import { loadRoster, savePeople, saveRoster } from '../../utils/sprintPlanning'
import { fixture, velocityContext } from './planningFixtures'

vi.mock('../../services/api', () => ({
  api: { teams: vi.fn(), sprintPlanningSetup: vi.fn(), sprintVelocityContext: vi.fn(), sprintPlan: vi.fn(), sprintCommit: vi.fn() },
}))

let host: HTMLDivElement, root: Root
let props: React.ComponentProps<typeof SprintPlanningPage>
const setup = (team = 'Alpha'): SprintPlanningSetup => ({
  team, sprints: [fixture().from_sprint, fixture().to_sprint], default_from_id: 's2', default_to_id: 's3',
  members: [{ name: 'Ava', unique_name: 'ava@test' }, { name: 'Ben', unique_name: 'ben@test' }],
  areas: ['Demo\\Alpha'], work_item_types: ['User Story'], default_types: ['User Story'], per_person: 6, active_days: 10, notes: [],
})
function element<T extends HTMLElement = HTMLElement>(selector: string): T {
  const found = host.querySelector<T>(selector)
  if (!found) throw new Error(`Missing element: ${selector}`)
  return found
}
const click = async (target: HTMLElement) => { await act(async () => target.click()) }
const generate = async () => click(element('[data-testid="spp-plan"]'))
async function render(overrides: Partial<typeof props> = {}) {
  props = { ...props, ...overrides }
  await act(async () => root.render(<SprintPlanningPage {...props} />))
}
async function remount() {
  await act(async () => root.unmount())
  root = createRoot(host)
  await render()
}
async function enter(selector: string, value: string) {
  await act(async () => {
    const control = element<HTMLInputElement>(selector)
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(control, value)
    control.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
async function changeTeam(team: string) {
  await act(async () => {
    const control = element<HTMLSelectElement>('[data-testid="spp-team"]')
    control.value = team
    control.dispatchEvent(new Event('change', { bubbles: true }))
  })
}
async function chooseAva() {
  await click(element('[data-testid="spp-edit-roster"]'))
  await click(element('input[aria-label="Roster Ben"]'))
  await click(element('[data-testid="spp-save-roster"]'))
}
beforeEach(() => {
  vi.resetAllMocks()
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  localStorage.clear()
  localStorage.setItem('ado_sprint_planning_team:org:demo', 'Alpha')
  savePeople('org', 'Demo', 'Alpha', fixture().people.map(member => ({ ...member, included: true, manual: false })))
  vi.mocked(api.teams).mockResolvedValue([{ id: 'alpha', name: 'Alpha' }, { id: 'beta', name: 'Beta' }])
  vi.mocked(api.sprintPlanningSetup).mockImplementation(async (_org, _project, team) => setup(team))
  vi.mocked(api.sprintVelocityContext).mockImplementation(async (_org, _project, _team, target) => velocityContext(target))
  vi.mocked(api.sprintPlan).mockResolvedValue(fixture())
  vi.mocked(api.sprintCommit).mockResolvedValue({ success: true, message: 'Committed', updated_count: 1, errors: [] })
  props = { organization: 'org', project: 'Demo', pat: 'test' }
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})
afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  localStorage.clear()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('team planning roster', () => {
  it('initially lists everyone, saves the selected subset, and restores it after remounting', async () => {
    await render()
    expect(host.querySelectorAll('[data-testid^="spp-person-"]')).toHaveLength(2)
    expect(element('[data-testid="spp-edit-roster"]').textContent).toBe('Edit team roster')
    await chooseAva()
    expect(loadRoster('org', 'Demo', 'Alpha')).toEqual(['ava@test'])
    expect(host.querySelector('[data-testid="spp-person-ben@test"]')).toBeNull()
    await remount()
    expect(host.querySelector('[data-testid="spp-person-ava@test"]')).not.toBeNull()
    expect(host.querySelector('[data-testid="spp-person-ben@test"]')).toBeNull()
    await generate()
    expect(vi.mocked(api.sprintPlan).mock.calls[0][0].people.map(member => member.unique_name)).toEqual(['ava@test'])
  })

  it('lets the editor search all candidates and cancel without changing the saved roster', async () => {
    saveRoster('org', 'Demo', 'Alpha', ['ava@test'])
    await render()
    await click(element('[data-testid="spp-edit-roster"]'))
    await enter('input[aria-label="Search roster candidates"]', 'BEN@TEST')
    expect(host.querySelector('input[aria-label="Roster Ava"]')).toBeNull()
    await click(element('input[aria-label="Roster Ben"]'))
    const cancel = [...host.querySelectorAll('button')].find(button => button.textContent === 'Cancel')!
    await click(cancel)
    expect(loadRoster('org', 'Demo', 'Alpha')).toEqual(['ava@test'])
    expect(host.querySelector('[data-testid="spp-person-ben@test"]')).toBeNull()
  })

  it('keeps an intentionally empty roster empty after remounting', async () => {
    await render()
    await click(element('[data-testid="spp-edit-roster"]'))
    await click([...host.querySelectorAll('button')].find(button => button.textContent === 'Clear selection')!)
    await click(element('[data-testid="spp-save-roster"]'))
    await remount()
    expect(loadRoster('org', 'Demo', 'Alpha')).toEqual([])
    expect(host.querySelectorAll('[data-testid^="spp-person-"]')).toHaveLength(0)
    expect(element<HTMLButtonElement>('[data-testid="spp-plan"]').disabled).toBe(true)
    await generate()
    expect(api.sprintPlan).not.toHaveBeenCalled()
  })

  it('keeps the saved team roster separate from temporary In plan checkboxes', async () => {
    saveRoster('org', 'Demo', 'Alpha', ['ava@test', 'ben@test'])
    await render()
    await click(element('input[aria-label="Plan Ben"]'))
    await generate()
    expect(vi.mocked(api.sprintPlan).mock.calls[0][0].people.map(member => member.unique_name)).toEqual(['ava@test'])
    await remount()
    expect(host.querySelector('[data-testid="spp-person-ben@test"]')).not.toBeNull()
    expect(element<HTMLInputElement>('input[aria-label="Plan Ben"]').checked).toBe(false)
    expect(loadRoster('org', 'Demo', 'Alpha')).toEqual(['ava@test', 'ben@test'])
  })

  it('isolates rosters by team, project and organization', async () => {
    saveRoster('org', 'Demo', 'Alpha', ['ava@test'])
    saveRoster('org', 'Demo', 'Beta', ['ben@test'])
    await render()
    await changeTeam('Beta')
    expect(host.querySelector('[data-testid="spp-person-ava@test"]')).toBeNull()
    expect(host.querySelector('[data-testid="spp-person-ben@test"]')).not.toBeNull()
    await changeTeam('Alpha')
    expect(host.querySelector('[data-testid="spp-person-ben@test"]')).toBeNull()
    localStorage.setItem('ado_sprint_planning_team:org:other', 'Alpha')
    await render({ project: 'Other' })
    expect(host.querySelectorAll('[data-testid^="spp-person-"]')).toHaveLength(2)
    localStorage.setItem('ado_sprint_planning_team:other:other', 'Alpha')
    await render({ organization: 'other' })
    expect(host.querySelectorAll('[data-testid^="spp-person-"]')).toHaveLength(2)
    expect(loadRoster('org', 'Demo', 'Alpha')).toEqual(['ava@test'])
  })

  it('refreshes candidates without changing saved membership, Capacity-tab availability or rules', async () => {
    saveRoster('org', 'Demo', 'Alpha', ['ava@test'])
    await render()
    await enter('[data-testid="spp-per-person"]', '4')
    await enter('[data-testid="spp-active-days"]', '7')
    vi.mocked(api.sprintPlanningSetup).mockResolvedValueOnce({
      ...setup(), members: [{ name: 'Ben', unique_name: 'ben@test' }, { name: 'Cora', unique_name: 'cora@test' }],
    })
    await click(element('[data-testid="spp-refresh-members"]'))
    expect(element<HTMLInputElement>('[data-testid="spp-per-person"]').value).toBe('4')
    expect(element<HTMLInputElement>('[data-testid="spp-active-days"]').value).toBe('7')
    expect(element('[data-testid="spp-days-ava@test"]').textContent).toBe('10')
    expect(element('[data-testid="spp-pto-ava@test"]').textContent).toBe('0')
    expect(host.querySelector('[data-testid="spp-person-cora@test"]')).toBeNull()
    await generate()
    expect(vi.mocked(api.sprintPlan).mock.calls[0][0].people).toEqual([
      expect.objectContaining({ unique_name: 'ava@test', areas: ['*'], working_days: 10, pto_days: 0 }),
    ])
    await click(element('[data-testid="spp-edit-roster"]'))
    expect(host.querySelector('input[aria-label="Roster Cora"]')).not.toBeNull()
    expect(element<HTMLInputElement>('input[aria-label="Roster Ava"]').checked).toBe(true)
    await remount()
    expect(host.querySelector('[data-testid="spp-person-ava@test"]')).not.toBeNull()
  })

  it('reports refresh failures without losing the roster or capacity edits', async () => {
    saveRoster('org', 'Demo', 'Alpha', ['ava@test'])
    await render()
    vi.mocked(api.sprintPlanningSetup).mockRejectedValueOnce(new Error('ADO unavailable'))
    await click(element('[data-testid="spp-refresh-members"]'))
    expect(element('[data-testid="spp-roster-error"]').textContent).toContain('ADO unavailable')
    expect(element('[data-testid="spp-days-ava@test"]').textContent).toBe('10')
    expect(loadRoster('org', 'Demo', 'Alpha')).toEqual(['ava@test'])
  })

  it('does not claim to save a roster when browser storage fails', async () => {
    saveRoster('org', 'Demo', 'Alpha', ['ava@test'])
    await render()
    await click(element('[data-testid="spp-edit-roster"]'))
    await click(element('input[aria-label="Roster Ben"]'))
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Storage blocked') })
    await click(element('[data-testid="spp-save-roster"]'))
    expect(element('[data-testid="spp-roster-error"]').textContent).toContain('could not be saved')
    expect(host.querySelector('[data-testid="spp-roster-editor"]')).not.toBeNull()
    expect(loadRoster('org', 'Demo', 'Alpha')).toEqual(['ava@test'])
    expect(host.querySelector('[data-testid="spp-person-ben@test"]')).toBeNull()
  })

  it('rejects a late refresh after the selected team changes', async () => {
    saveRoster('org', 'Demo', 'Alpha', ['ava@test'])
    saveRoster('org', 'Demo', 'Beta', ['ben@test'])
    await render()
    let resolve!: (value: SprintPlanningSetup) => void
    vi.mocked(api.sprintPlanningSetup).mockReturnValueOnce(new Promise(done => { resolve = done }))
    await click(element('[data-testid="spp-refresh-members"]'))
    await changeTeam('Beta')
    await act(async () => resolve({ ...setup(), members: [{ name: 'Wrong', unique_name: 'wrong@test' }] }))
    expect(host.querySelector('[data-testid="spp-person-ben@test"]')).not.toBeNull()
    expect(host.querySelector('[data-testid="spp-person-wrong@test"]')).toBeNull()
  })

  it('invalidates old plans and in-flight responses when opening the roster editor', async () => {
    await render()
    await generate()
    await click(element('[data-testid="spp-edit-roster"]'))
    expect(host.querySelector('[data-testid="spp-result"]')).toBeNull()
    expect(element<HTMLButtonElement>('[data-testid="spp-plan"]').disabled).toBe(true)
    await click(element('[data-testid="spp-save-roster"]'))
    let resolve!: (value: SprintPlan) => void
    vi.mocked(api.sprintPlan).mockReturnValueOnce(new Promise(done => { resolve = done }))
    await generate()
    await click(element('[data-testid="spp-edit-roster"]'))
    await act(async () => resolve(fixture()))
    expect(host.querySelector('[data-testid="spp-result"]')).toBeNull()
    expect(api.sprintCommit).not.toHaveBeenCalled()
  })

  it('allows adding a manual candidate and selecting that person without discarding the saved roster', async () => {
    saveRoster('org', 'Demo', 'Alpha', ['ava@test'])
    await render()
    await enter('[data-testid="spp-add-person"]', 'cora@test')
    await click([...host.querySelectorAll('button')].find(button => button.textContent?.trim() === 'Add')!)
    expect(loadRoster('org', 'Demo', 'Alpha')).toEqual(['ava@test'])
    await click(element('[data-testid="spp-edit-roster"]'))
    await click(element('input[aria-label="Roster Cora"]'))
    await click(element('[data-testid="spp-save-roster"]'))
    await remount()
    expect(host.querySelector('[data-testid="spp-person-cora@test"]')).not.toBeNull()
    expect(loadRoster('org', 'Demo', 'Alpha')).toEqual(['ava@test', 'cora@test'])
  })
})
