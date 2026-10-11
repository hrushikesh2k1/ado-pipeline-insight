import { describe, it, expect } from 'vitest'
import {
  buildDeliverablesReport,
  formatReportDate,
  getDeliverablesStorageKey,
  isItemClosedInSprint
} from '../../utils/deliverablesReport'
import type { AdoSprintBoardResponse } from '../../types/api'

describe('deliverablesReport utilities', () => {
  const mockBoardData: AdoSprintBoardResponse = {
    team: {
      id: 'team-1',
      name: 'Core Team'
    },
    iteration: {
      id: 'iter-1',
      name: 'Sprint 26-09',
      path: 'Project\\Sprint 26-09',
      start_date: '2026-09-01T00:00:00Z',
      finish_date: '2026-09-30T00:00:00Z',
      time_frame: 'past'
    },
    work_items: [
      {
        id: 101,
        title: 'Story Alpha',
        work_item_type: 'User Story',
        state: 'Closed',
        assigned_to_name: 'Harish Boora',
        completed_work: 8,
        remaining_work: 0,
        is_closed_without_hours: false,
        is_stale_in_review: false,
        description: 'Story challenge description',
        acceptance_criteria: 'All DoD verified'
      },
      {
        id: 102,
        title: 'Bug Beta',
        work_item_type: 'Bug',
        state: 'Active',
        assigned_to_name: 'John Doe',
        completed_work: 2,
        remaining_work: 5,
        is_closed_without_hours: false,
        is_stale_in_review: false
      },
      {
        id: 201,
        title: 'Child Task of Alpha',
        work_item_type: 'Task',
        state: 'Closed',
        parent_id: 101,
        completed_work: 4,
        is_closed_without_hours: false,
        is_stale_in_review: false
      }
    ],
    checks_summary: {
      total_tasks: 1,
      tasks_closed_count: 1,
      tasks_closed_without_hours_count: 0,
      total_user_stories: 2,
      stories_in_review_count: 0,
      stories_in_review_stale_count: 0,
      flagged_item_ids: []
    }
  }

  it('builds a complete deliverables report with separated completed and pending sections', () => {
    const report = buildDeliverablesReport(
      mockBoardData,
      'my-org',
      'my-project',
      'team-1',
      'iter-1',
      'Sprint 26-09',
      'fresh'
    )

    expect(report.organization).toBe('my-org')
    expect(report.project).toBe('my-project')
    expect(report.status).toBe('fresh')
    expect(report.completedDeliverables.length).toBe(1)
    expect(report.completedDeliverables[0].id).toBe(101)
    expect(report.completedDeliverables[0].hours_delivered).toBe(12) // 8 + 4

    expect(report.pendingDeliverables.length).toBe(1)
    expect(report.pendingDeliverables[0].id).toBe(102)
    expect(report.pendingDeliverables[0].state).toBe('Active')

    expect(report.capacityEffortSummary.totalStories).toBe(2)
    expect(report.capacityEffortSummary.closedStoriesCount).toBe(1)
    expect(report.capacityEffortSummary.completionRatePct).toBe(50)

    expect(report.memberContributions.length).toBeGreaterThanOrEqual(2)
  })

  it('generates consistent storage keys', () => {
    const key = getDeliverablesStorageKey('Org', 'Project', 'Team1', 'Iter1')
    expect(key).toBe('ado_deliverables_report_org:project:team1:iter1')
  })

  it('formats dates cleanly', () => {
    const formatted = formatReportDate('2026-10-10T15:30:00Z')
    expect(formatted).toContain('2026')
    expect(formatted).toContain('Oct')
  })

  it('correctly checks whether an item was closed in the sprint timeframe', () => {
    const iter = {
      start_date: '2026-09-01T00:00:00Z',
      finish_date: '2026-09-30T00:00:00Z'
    }

    // Closed within September
    expect(
      isItemClosedInSprint(
        { state: 'Closed', closed_date: '2026-09-15T12:00:00Z' },
        iter
      )
    ).toBe(true)

    // Closed on finish date evening (same day)
    expect(
      isItemClosedInSprint(
        { state: 'Closed', closed_date: '2026-09-30T18:45:00Z' },
        iter
      )
    ).toBe(true)

    // Closed in October -> false
    expect(
      isItemClosedInSprint(
        { state: 'Closed', closed_date: '2026-10-02T10:00:00Z' },
        iter
      )
    ).toBe(false)

    // Closed in August -> false
    expect(
      isItemClosedInSprint(
        { state: 'Closed', closed_date: '2026-08-30T10:00:00Z' },
        iter
      )
    ).toBe(false)

    // Active item -> false
    expect(
      isItemClosedInSprint(
        { state: 'Active', closed_date: '2026-09-15T12:00:00Z' },
        iter
      )
    ).toBe(false)
  })
})
