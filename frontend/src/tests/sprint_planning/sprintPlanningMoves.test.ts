import { describe, expect, it } from 'vitest'
import { commitAssignments, rankGoalBacklog, recalculatePlan, reassignStory } from '../../utils/sprintPlanning'
import { fixture, person, story } from './planningFixtures'

describe('manual draft moves', () => {
  it('reserves half carryover points after manual moves and retains forecast diagnostics', () => {
    const plan = fixture()
    plan.people = plan.people.map(person => ({ ...person, velocity_based: true, forecast_status: 'ready', capacity_points: 5, points_capacity: 5 }))
    const initial = recalculatePlan(plan)
    expect(initial.people[0]).toMatchObject({ points_carried: 3, points_reserved: 1.5, points_open: 3.5 })
    const moved = reassignStory(initial, 1, 'ben@test')
    expect(moved.people[0].points_reserved).toBe(0)
    expect(moved.people[1]).toMatchObject({ points_reserved: 1.5, points_open: 3.5 })
    const assigned = reassignStory(moved, 2, 'ben@test')
    expect(assigned.people[1].points_reserved).toBe(4.5)
    expect(assigned.people[1].points_over_by).toBe(0)
    expect(assigned.people[1].warnings.join(' ')).toContain('50%')
    assigned.people[1].forecast_status = 'unavailable'
    assigned.people[1].forecast_note = 'Historical data missing'
    const unavailable = recalculatePlan(assigned)
    expect(unavailable.people[1].warnings.join(' ')).toContain('Historical data missing')
    expect(unavailable.people[1].warnings.join(' ')).toContain('Manual or existing assignments')
  })

  it('ranks distinct topics with single-word evidence restricted to titles and tags', () => {
    const stories = [
      story({ id: 1, title: 'OAuth integration' }),
      story({ id: 2, title: 'OAuth monitoring', tags: ['OAuth'] }),
      story({ id: 3, title: 'Observe systems', tags: ['MONITORING'] }),
      story({ id: 4, title: 'Reauthentication', description: 'The other work' }),
    ]
    expect(rankGoalBacklog(stories, 'The OAuth and monitoring').map(item => [item.story.id, item.matches])).toEqual([
      [2, ['oauth', 'monitoring']], [1, ['oauth']], [3, ['monitoring']], [4, []],
    ])
    expect(stories.map(s => s.id)).toEqual([1, 2, 3, 4])
    expect(rankGoalBacklog(stories, '').map(item => item.story.id)).toEqual([1, 2, 3, 4])
    expect(rankGoalBacklog(stories, 'the and to').every(item => item.matches.length === 0)).toBe(true)
  })

  it('rejects generic PostgreSQL metrics overlap while preserving explicit cost and ingestion matches', () => {
    const stories = [
      story({ id: 1, title: 'Enable the enhanced metrics on PostgreSQL', description: 'Collect high resolution data and monitor metrics. Cost may vary.' }),
      story({ id: 2, title: 'Reduce Log Analytics ingestion costs' }),
      story({ id: 3, title: 'Filter unnecessary telemetry before ingestion', description: 'Reduce data ingestion volume before exporting logs.' }),
      story({ id: 4, title: 'High availability', tags: ['data'] }),
      story({ id: 5, title: 'Control spend', tags: ['Data-Ingestion'] }),
    ]
    const ranked = rankGoalBacklog(stories, 'cost, high data ingestion')
    expect(ranked.map(item => [item.story.id, item.matches])).toEqual([
      [2, ['cost']], [3, ['data ingestion']], [5, ['data ingestion']], [1, []], [4, []],
    ])
    expect(ranked[1].evidence).toEqual([{ topic: 'data ingestion', source: 'description', excerpt: 'Reduce data ingestion volume before exporting logs.' }])
    expect(ranked[2].evidence[0].source).toBe('tag')
  })

  it('does not combine unrelated words across fields or match substrings, generic topics, or weak descriptions', () => {
    const stories = [
      story({ id: 1, title: 'Data export', description: 'Ingestion setup with high cost', tags: ['ingestion'] }),
      story({ id: 2, title: 'Costume update', description: 'Data retention and ingestion configuration' }),
    ]
    expect(rankGoalBacklog(stories, 'cost, high data ingestion').every(item => item.matches.length === 0)).toBe(true)
    expect(rankGoalBacklog(stories, 'high, data, enhanced metrics').every(item => item.matches.length === 0)).toBe(true)
    expect(rankGoalBacklog(stories, '').map(item => item.story.id)).toEqual([1, 2])
  })

  it('preserves topic phrases with case, punctuation, and stopwords and returns focused evidence', () => {
    const text = `${'Unrelated context. '.repeat(20)}DATA ingestion pipeline.${' Following detail.'.repeat(20)}`
    const ranked = rankGoalBacklog([story({ description: text, title: 'Pipeline improvement' })], 'High data ingestion; OAuth')
    expect(ranked[0].matches).toEqual(['data ingestion'])
    expect(ranked[0].evidence[0].excerpt).toContain('DATA ingestion')
    expect(ranked[0].evidence[0].excerpt.length).toBeLessThan(200)
    expect(rankGoalBacklog([story({ title: 'Data platform ingestion' })], 'data ingestion')[0].matches).toEqual([])
  })

  it('assigns a remaining backlog story absent from the legacy unplaced list without duplication', () => {
    const plan = fixture()
    plan.available_backlog = [story({ id: 9, iteration_path: 'Demo' })]
    const assigned = reassignStory(plan, 9, 'ben@test')
    expect(assigned.available_backlog).toEqual([])
    expect(assigned.people[1].new[0].id).toBe(9)
    expect(assigned.summary.stories_planned).toBe(2)
    const removed = reassignStory(assigned, 9, '')
    expect(removed.available_backlog?.map(s => s.id)).toEqual([9])
    expect(reassignStory(removed, 9, 'ben@test').available_backlog).toEqual([])
    expect(plan.available_backlog).toHaveLength(1)
  })

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
