import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SprintPlanningPage } from '../../components/SprintPlanningPage'
import { api } from '../../services/api'
import { fixture, story, velocityContext } from './planningFixtures'

vi.mock('../../services/api', () => ({
  api: { teams: vi.fn(), sprintPlanningSetup: vi.fn(), sprintVelocityContext: vi.fn(), sprintPlan: vi.fn(), sprintCommit: vi.fn(), workItemComments: vi.fn() },
}))

let host: HTMLDivElement, root: Root
const comments = [1, 2, 3, 4, 5].map(day => ({ author: 'Ava', date: `2026-10-0${day}T12:00:00Z`, text: `Comment ${day}` }))
const click = async (target: HTMLElement) => { await act(async () => target.click()) }
const button = (parent: Element, text: string) => {
  const found = Array.from(parent.querySelectorAll('button')).find(candidate => candidate.textContent?.includes(text))
  if (!found) throw new Error(`Missing button: ${text}`)
  return found
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  localStorage.clear()
  localStorage.setItem('ado_sprint_planning_team:org:demo', 'Alpha')
  vi.mocked(api.teams).mockResolvedValue([{ id: 'alpha', name: 'Alpha' }])
  vi.mocked(api.sprintVelocityContext).mockImplementation(async (_org, _project, _team, target) => velocityContext(target))
  vi.mocked(api.sprintPlanningSetup).mockResolvedValue({
    team: 'Alpha', sprints: [fixture().from_sprint, fixture().to_sprint], default_from_id: 's2', default_to_id: 's3',
    members: [{ name: 'Ava', unique_name: 'ava@test' }], areas: ['*'], work_item_types: ['User Story'],
    default_types: ['User Story'], per_person: 6, active_days: 10, notes: [],
  })
  const plan = fixture()
  plan.flagged[0].comments = comments
  plan.people[0].carried[0].comments = comments
  plan.people[0].already_planned = [story({ id: 3, state: 'Resolved', flags: [], comments: [] })]
  plan.people[0].new = [story({ id: 4, state: 'New', flags: [], comments: null })]
  plan.outside_plan = [story({ id: 5, comments: null })]
  plan.unplaced[0].story.comments = null
  vi.mocked(api.sprintPlan).mockResolvedValue(plan)
  vi.mocked(api.workItemComments).mockResolvedValue([...comments].reverse())
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})

afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  localStorage.clear()
  vi.unstubAllGlobals()
})

async function generate() {
  await act(async () => root.render(<SprintPlanningPage organization="org" project="Demo" pat="test-token" />))
  await click(host.querySelector<HTMLButtonElement>('[data-testid="spp-plan"]')!)
}

async function filterAttention(value: string) {
  await act(async () => {
    const select = host.querySelector<HTMLSelectElement>('select[aria-label="Filter stories needing attention"]')!
    select.value = value
    select.dispatchEvent(new Event('change', { bubbles: true }))
  })
}

it('filters attention by flag, includes dual-flag stories, and does not change workloads or summary', async () => {
  const plan = fixture()
  const blocked = story({ id: 10, flags: [{ code: 'blocked', reason: 'Blocked' }] })
  const active = story({ id: 11, flags: [{ code: 'active_too_long', reason: 'Active too long' }] })
  const both = story({ id: 12, flags: [...blocked.flags, ...active.flags] })
  plan.flagged = [blocked, active, both]
  vi.mocked(api.sprintPlan).mockResolvedValue(plan)
  await generate()
  const section = host.querySelector('[data-testid="spp-flagged"]')!
  const workloads = host.querySelector('[data-testid="spp-workload-pane"]')!.innerHTML
  const summary = host.querySelector('[data-testid="spp-summary"]')!.innerHTML
  const ids = () => [...section.querySelectorAll('.sppFlagged')].map(card => card.getAttribute('data-testid'))
  expect(ids()).toEqual(['spp-flagged-10', 'spp-flagged-11', 'spp-flagged-12'])
  await filterAttention('blocked')
  expect(ids()).toEqual(['spp-flagged-10', 'spp-flagged-12'])
  expect(section.textContent).toContain('Showing 2 of 3')
  await filterAttention('active_too_long')
  expect(ids()).toEqual(['spp-flagged-11', 'spp-flagged-12'])
  expect(host.querySelector('[data-testid="spp-workload-pane"]')!.innerHTML).toBe(workloads)
  expect(host.querySelector('[data-testid="spp-summary"]')!.innerHTML).toBe(summary)
  expect(api.sprintPlan).toHaveBeenCalledTimes(1)
  expect(api.sprintCommit).not.toHaveBeenCalled()
  await filterAttention('all')
  expect(ids()).toHaveLength(3)
})

it('shows an empty filter result and resets to all when generating a new plan', async () => {
  await generate()
  await filterAttention('active_too_long')
  const section = host.querySelector('[data-testid="spp-flagged"]')!
  expect(section.querySelectorAll('.sppFlagged')).toHaveLength(0)
  expect(section.textContent).toContain('No stories match this attention filter.')
  expect(section.textContent).toContain('Showing 0 of 1')
  await click(host.querySelector<HTMLButtonElement>('[data-testid="spp-plan"]')!)
  expect(host.querySelector<HTMLSelectElement>('select[aria-label="Filter stories needing attention"]')!.value).toBe('all')
  expect(host.querySelectorAll('.sppFlagged')).toHaveLength(1)
})

it('hides comments for every story, including flagged, carried, resolved, new, unplaced and outside-plan stories', async () => {
  await generate()
  expect(host.querySelectorAll('[data-testid="spp-comment"]')).toHaveLength(0)
  expect(Array.from(host.querySelectorAll('button')).filter(b => b.textContent?.includes('View Recent Comments'))).toHaveLength(6)
  expect(api.workItemComments).not.toHaveBeenCalled()
})

it('expands only the chosen story, limits to the latest three, and collapses again', async () => {
  await generate()
  const flagged = host.querySelector('[data-testid="spp-flagged-1"]')!
  const toggle = button(flagged, 'View Recent Comments')
  expect(toggle.getAttribute('aria-expanded')).toBe('false')
  await click(toggle)
  expect(toggle.getAttribute('aria-expanded')).toBe('true')
  const shown = Array.from(flagged.querySelectorAll('[data-testid="spp-comment"] p')).map(p => p.textContent)
  expect(shown).toEqual(['Comment 3', 'Comment 4', 'Comment 5'])
  expect(host.querySelectorAll('[data-testid="spp-comment"]')).toHaveLength(3)
  expect(api.workItemComments).not.toHaveBeenCalled()
  await click(button(flagged, 'Hide Recent Comments'))
  expect(host.querySelectorAll('[data-testid="spp-comment"]')).toHaveLength(0)
})

it('loads non-prefetched comments on demand with top=3 and caches them for reopening', async () => {
  await generate()
  const row = host.querySelector('[data-testid="spp-story-4"]')!
  await click(button(row, 'View Recent Comments'))
  expect(api.workItemComments).toHaveBeenCalledWith('org', 'Demo', 4, 3, 'test-token')
  expect(Array.from(row.querySelectorAll('[data-testid="spp-comment"] p')).map(p => p.textContent)).toEqual(['Comment 3', 'Comment 4', 'Comment 5'])
  await click(button(row, 'Hide Recent Comments'))
  await click(button(row, 'View Recent Comments'))
  expect(api.workItemComments).toHaveBeenCalledTimes(1)
})

it('shows empty comments only after opening and displays retryable errors instead of an empty success', async () => {
  await generate()
  const resolved = host.querySelector('[data-testid="spp-story-3"]')!
  expect(resolved.textContent).not.toContain('No comments on this story.')
  await click(button(resolved, 'View Recent Comments'))
  expect(resolved.textContent).toContain('No comments on this story.')
  vi.mocked(api.workItemComments).mockRejectedValueOnce(new Error('Permission denied')).mockResolvedValueOnce([])
  const row = host.querySelector('[data-testid="spp-story-4"]')!
  await click(button(row, 'View Recent Comments'))
  expect(row.querySelector('[role="alert"]')?.textContent).toContain('Permission denied')
  expect(row.textContent).not.toContain('No comments on this story.')
  await click(button(row, 'Hide Recent Comments'))
  await click(button(row, 'View Recent Comments'))
  expect(row.querySelector('[role="alert"]')).toBeNull()
  expect(row.textContent).toContain('No comments on this story.')
})
