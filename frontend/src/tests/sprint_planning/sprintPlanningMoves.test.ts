import { describe, expect, it } from 'vitest'
import { commitAssignments, recalculatePlan, reassignStory } from '../../utils/sprintPlanning'
import { fixture, person, story } from './planningFixtures'

describe('manual draft moves', () => {
  it('assigns an unplaced story and refreshes person and sprint counters', () => {
    const plan = fixture(), copy = JSON.stringify(plan)
    const result = reassignStory(plan, 2, 'ben@test')
    expect(JSON.stringify(plan)).toBe(copy)
    expect(result.people[1].new.map(s => s.id)).toEqual([2])
    expect(result.people[1]).toMatchObject({ total: 1, points_new: 3, points_planned: 3, points_open: 5 })
    expect(result.summary).toMatchObject({ stories_planned: 2, new: 1, unplaced: 0, total_points_planned: 6 })
    expect(result.unplaced_total).toBe(0)
  })
  it('removes flags and all summary contributions when a story leaves the plan', () => {
    const result = reassignStory(fixture(), 1, '')
    expect(result.flagged).toEqual([])
    expect(result.summary).toMatchObject({ stories_planned: 0, carried: 0, flagged: 0, blocked: 0, total_points_planned: 0, risk_score: 'Low', unplaced: 2 })
    expect(commitAssignments(result)).toEqual([])
  })
  it('restores the source lane and planned owner when a removed carryover is reassigned', () => {
    const result = reassignStory(reassignStory(fixture(), 1, ''), 1, 'ben@test')
    expect(result.people[1].carried[0]).toMatchObject({ id: 1, assigned_to: 'Ben', assigned_unique: 'ben@test' })
    expect(result.people[1].new).toEqual([])
    expect(result.summary).toMatchObject({ carried: 1, new: 0, blocked: 1 })
    expect(result.flagged[0].assigned_to).toBe('Ben')
  })
  it('keeps omitted unplaced counts instead of replacing them with the visible list length', () => {
    const plan = fixture(); plan.unplaced_total = 50
    expect(reassignStory(plan, 2, 'ben@test').unplaced_total).toBe(49)
    expect(reassignStory(plan, 1, '').unplaced_total).toBe(51)
  })
  it('does not lose a story for an invalid person or an unchanged selection', () => {
    const plan = fixture()
    expect(reassignStory(plan, 1, 'missing')).toBe(plan)
    expect(reassignStory(plan, 999, 'ben@test')).toBe(plan)
    expect(reassignStory(plan, 1, 'ava@test')).toBe(plan)
  })
  it('uses unique identities for people with the same display name', () => {
    const plan = fixture(); plan.people[1].name = 'Ava'
    const result = reassignStory(plan, 1, 'ben@test')
    expect(result.people[0].carried).toEqual([])
    expect(result.people[1].carried[0].id).toBe(1)
  })
  it('recalculates warnings and risk when a zero-capacity person receives a manual override', () => {
    const plan = fixture(); plan.people[1].points_capacity = 0
    const result = reassignStory(plan, 2, 'ben@test')
    expect(result.people[1].points_over_by).toBe(3)
    expect(result.people[1].warnings.join(' ')).toContain('Capacity exceeded')
    expect(result.summary.risk_score).toBe('High')
  })
  it('does not remove flagged items owned outside the planning roster', () => {
    const plan = fixture(); plan.outside_plan = [story({ id: 3, assigned_to: 'Outside' })]
    const result = reassignStory(plan, 1, '')
    expect(result.flagged.map(s => s.id)).toEqual([3])
  })
  it('deduplicates exact assignments and rejects conflicting owners', () => {
    const plan = fixture(); plan.people[0].new.push(story())
    expect(commitAssignments(plan)).toHaveLength(1)
    plan.people[1].new.push(story())
    expect(() => commitAssignments(plan)).toThrow('conflicting planned owners')
  })
  it('summarizes already-planned points separately from new work', () => {
    const plan = fixture(); plan.people = [person({ carried: [], already_planned: [story({ iteration_path: 'Demo\\Sprint 3' })] })]
    const result = recalculatePlan(plan)
    expect(result.people[0]).toMatchObject({ points_already_planned: 3, points_new: 0, points_carried: 0 })
    expect(result.summary).toMatchObject({ already_planned: 1, carried: 0, new: 0 })
  })
})
