// @vitest-environment jsdom
import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { LegacySprintPlanningPage as SprintPlanningPage } from '../../components/SprintPlanningPage'
import { api } from '../../services/api'
import type { SprintPlan } from '../../types/api'
import { fixture } from './planningFixtures'

vi.mock('../../services/api', () => ({ api: { teams: vi.fn(), sprintPlanningSetup: vi.fn(), sprintPlan: vi.fn(), sprintCommit: vi.fn() } }))
let host: HTMLDivElement, root: Root
const setup = () => ({ team: 'Alpha', sprints: [fixture().from_sprint, fixture().to_sprint], default_to_id: 's3', default_from_id: 's2',
  members: [{ name: 'Ava', unique_name: 'ava@test' }, { name: 'Ben', unique_name: 'ben@test' }], areas: ['Demo\\Alpha'],
  work_item_types: ['User Story'], default_types: ['User Story'], per_person: 6, active_days: 10, notes: [] })
const button = (name: string) => [...host.querySelectorAll('button')].find(b => b.textContent?.trim() === name) as HTMLButtonElement
const click = async (target: Element) => { await act(async () => { (target as HTMLElement).click() }) }
const generate = async () => click(host.querySelector('[data-testid="spp-plan"]')!)
const change = async (selector: string, value: string) => {
  await act(async () => { const el = host.querySelector(selector) as HTMLSelectElement; el.value = value; el.dispatchEvent(new Event('change', { bubbles: true })) })
}
async function mount() { await act(async () => { root.render(<SprintPlanningPage organization="org" project="Demo" pat="test" />) }) }

beforeEach(() => {
  vi.clearAllMocks()
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  localStorage.clear()
  localStorage.setItem('ado_sprint_planning_team:org:demo', 'Alpha')
  localStorage.setItem('ado_sprint_planning:org:demo:alpha', JSON.stringify(fixture().people.map(p => ({ ...p, included: true, manual: false }))))
  vi.mocked(api.teams).mockResolvedValue([{ id: 't', name: 'Alpha' }])
  vi.mocked(api.sprintPlanningSetup).mockResolvedValue(setup())
  vi.mocked(api.sprintPlan).mockResolvedValue(fixture())
  vi.mocked(api.sprintCommit).mockResolvedValue({ success: true, message: 'Updated', updated_count: 1, errors: [] })
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
})
afterEach(async () => { await act(async () => root.unmount()); host.remove() })

it('assigns an unplaced work item through its dropdown and includes it in the confirmed commit', async () => {
  await mount(); await generate()
  await change('select[aria-label="Reassign story 2"]', 'ben@test')
  expect(host.querySelector('[data-testid="spp-unplaced"]')).toBeNull()
  await click(button('Commit to Azure DevOps')); await click(button('Confirm & Commit'))
  expect(api.sprintCommit).toHaveBeenCalledWith(expect.objectContaining({ to_iteration_id: 's3', to_iteration_path: 'Demo\\Sprint 3',
    assignments: [{ story_id: 1, assigned_to: 'ava@test' }, { story_id: 2, assigned_to: 'ben@test' }] }))
})

it('removes a flagged story from the draft and flags without claiming an Azure backlog write', async () => {
  await mount(); await generate(); await click(button('Remove from plan'))
  expect(host.querySelector('[data-testid="spp-flagged-1"]')).toBeNull()
  expect(host.textContent).toContain('Excluded manually from this draft')
  expect(api.sprintCommit).not.toHaveBeenCalled()
})

it('invalidates the plan and closes confirmation when capacity settings change', async () => {
  await mount(); await generate(); await click(button('Commit to Azure DevOps'))
  await click(button('Story Count'))
  expect(host.querySelector('[data-testid="spp-result"]')).toBeNull()
  expect(button('Confirm & Commit')).toBeUndefined()
  expect(api.sprintCommit).not.toHaveBeenCalled()
})

it('discards a plan response arriving after the settings changed', async () => {
  let resolve!: (value: SprintPlan) => void
  vi.mocked(api.sprintPlan).mockReturnValue(new Promise(r => { resolve = r }))
  await mount(); await generate(); await click(button('Story Count'))
  await act(async () => resolve(fixture()))
  expect(host.querySelector('[data-testid="spp-result"]')).toBeNull()
  expect(button('Commit to Azure DevOps')).toBeUndefined()
})

it('clears an old plan when regeneration fails', async () => {
  await mount(); await generate()
  vi.mocked(api.sprintPlan).mockRejectedValueOnce(new Error('Azure DevOps is unavailable'))
  await generate()
  expect(host.querySelector('[data-testid="spp-result"]')).toBeNull()
  expect(host.textContent).toContain('Azure DevOps is unavailable')
})

it('shows failed work item IDs and details after a partial commit', async () => {
  vi.mocked(api.sprintCommit).mockResolvedValue({ success: false, message: 'Updated 1 item, 1 error', updated_count: 1, errors: ['#12: Assignment not allowed'] })
  await mount(); await generate(); await click(button('Commit to Azure DevOps')); await click(button('Confirm & Commit'))
  expect(host.querySelector('[data-testid="spp-commit-result"]')?.textContent).toContain('#12: Assignment not allowed')
})

it('shows zero point capacity accurately instead of switching to story counts', async () => {
  const plan = fixture(); plan.people[0].points_capacity = 0; plan.people[0].points_planned = 3
  vi.mocked(api.sprintPlan).mockResolvedValue(plan)
  await mount(); await generate()
  expect(host.querySelector('[data-testid="spp-card-ava@test"]')?.textContent).toContain('3 of 0 pts')
})

it('disables planning and reassignment while a commit is in flight', async () => {
  let resolve!: (value: Awaited<ReturnType<typeof api.sprintCommit>>) => void
  vi.mocked(api.sprintCommit).mockReturnValue(new Promise(r => { resolve = r }))
  await mount(); await generate(); await click(button('Commit to Azure DevOps')); await click(button('Confirm & Commit'))
  expect(host.querySelector('fieldset')?.disabled).toBe(true)
  expect(button('Committing…')?.disabled).toBe(true)
  await act(async () => resolve({ success: true, message: 'Updated', updated_count: 1, errors: [] }))
})


const input = async (selector: string, value: string) => {
  await act(async () => {
    const element = host.querySelector(selector) as HTMLInputElement
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(element, value)
    element.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

it.each([
  ['[data-testid="spp-per-person"]', '3'],
  ['[data-testid="spp-active-days"]', '4'],
  ['[data-testid="spp-tags-filter"]', 'Changed'],
  ['[data-testid="spp-area-filter"]', 'AnotherArea'],
  ['input[title="Working days in sprint"]', '0'],
  ['input[title="PTO / Leave days"]', '10'],
])('invalidates the generated plan after editing %s', async (selector, value) => {
  await mount(); await generate(); await input(selector, value)
  expect(host.querySelector('[data-testid="spp-result"]')).toBeNull()
})

it('sends zero working days as zero, instead of replacing it with ten', async () => {
  await mount(); await input('input[title="Working days in sprint"]', '0'); await generate()
  expect(vi.mocked(api.sprintPlan).mock.calls[0][0].people[0].working_days).toBe(0)
})

it('invalidates generated assignments immediately when a target sprint changes', async () => {
  await mount(); await generate(); await change('[data-testid="spp-to"]', 's2')
  expect(host.querySelector('[data-testid="spp-result"]')).toBeNull()
  expect(api.sprintCommit).not.toHaveBeenCalled()
})

it('does not restore an old team setup when its request finishes late', async () => {
  let resolve!: (value: ReturnType<typeof setup>) => void
  vi.mocked(api.teams).mockResolvedValue([{ id: 'a', name: 'Alpha' }, { id: 'b', name: 'Beta' }])
  vi.mocked(api.sprintPlanningSetup).mockImplementationOnce(() => new Promise(r => { resolve = r }))
    .mockResolvedValueOnce({ ...setup(), team: 'Beta', members: [{ name: 'New Member', unique_name: 'new@test' }] })
  await mount(); await change('[data-testid="spp-team"]', 'Beta')
  expect(host.querySelector('[data-testid="spp-person-new@test"]')).not.toBeNull()
  await act(async () => resolve(setup()))
  expect(host.querySelector('[data-testid="spp-person-new@test"]')).not.toBeNull()
  expect(host.querySelector('[data-testid="spp-person-ava@test"]')).toBeNull()
})
