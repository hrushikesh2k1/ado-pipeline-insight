import { describe, it, expect } from 'vitest'
import {
  detectBlockedItems,
  detectReviewBottlenecks,
  detectWorkloadGaps,
  buildStandupSummary,
  generateStandupDigest
} from '../../utils/standupInsights'
import type { AdoWorkItem } from '../../types/api'

describe('standupInsights', () => {
  const mockWorkItems: AdoWorkItem[] = [
    // 1. Blocked via tag
    {
      id: 101,
      title: 'VPN Disconnection Alert',
      work_item_type: 'User Story',
      state: 'Active',
      tags: 'Monitoring, Blocked',
      assigned_to_name: 'Alice',
      is_closed_without_hours: false,
      is_stale_in_review: false,
      story_points: 3
    },
    // 2. Blocked via state
    {
      id: 102,
      title: 'Database Migration Script',
      work_item_type: 'Task',
      state: 'Blocked',
      assigned_to_name: 'Bob',
      is_closed_without_hours: false,
      is_stale_in_review: false,
      remaining_work: 4
    },
    // 3. Blocked via is_blocked flag
    {
      id: 103,
      title: 'Grafana Dashboard Setup',
      work_item_type: 'User Story',
      state: 'In Progress',
      is_blocked: true,
      assigned_to_name: 'Charlie',
      is_closed_without_hours: false,
      is_stale_in_review: false
    },
    // 4. Closed item with blocked tag (should be IGNORED because it is already closed)
    {
      id: 104,
      title: 'Legacy Auth Clean up',
      work_item_type: 'User Story',
      state: 'Closed',
      tags: 'Blocked',
      assigned_to_name: 'Alice',
      is_closed_without_hours: false,
      is_stale_in_review: false
    },
    // 5. In Review bottleneck (stale)
    {
      id: 105,
      title: 'PR Review Bottleneck Story',
      work_item_type: 'User Story',
      state: 'In Review',
      business_days_in_review: 4,
      is_stale_in_review: true,
      assigned_to_name: 'Dave',
      is_closed_without_hours: false
    },
    // 6. Normal In Progress task
    {
      id: 106,
      title: 'Normal Active Task',
      work_item_type: 'Task',
      state: 'In Progress',
      assigned_to_name: 'Alice',
      is_closed_without_hours: false,
      is_stale_in_review: false
    },
    // 7. To Do task assigned to Dave
    {
      id: 107,
      title: 'Next sprint prep task',
      work_item_type: 'Task',
      state: 'To Do',
      assigned_to_name: 'Dave',
      is_closed_without_hours: false,
      is_stale_in_review: false
    }
  ]

  it('detects blocked items correctly', () => {
    const blocked = detectBlockedItems(mockWorkItems)
    expect(blocked.map(b => b.id)).toEqual([101, 102, 103])
    expect(blocked[0].reason).toContain('Blocked')
    expect(blocked[1].reason).toBe('State: Blocked')
  })

  it('detects review bottlenecks correctly', () => {
    const bottlenecks = detectReviewBottlenecks(mockWorkItems)
    expect(bottlenecks.map(b => b.id)).toEqual([105])
    expect(bottlenecks[0].business_days_in_review).toBe(4)
  })

  it('detects workload gaps for team members with no active tasks in progress', () => {
    const members = [
      { name: 'Alice', capacity_per_day: 6 },
      { name: 'Bob', capacity_per_day: 6 },
      { name: 'Charlie', capacity_per_day: 6 },
      { name: 'Dave', capacity_per_day: 6 }
    ]

    const gaps = detectWorkloadGaps(mockWorkItems, members)

    // Alice has 106 in progress -> no gap
    // Charlie has 103 in progress -> no gap
    // Bob has 102 (Blocked) -> no in-progress -> GAP
    // Dave has 105 (In Review) and 107 (To Do) -> no in-progress -> GAP
    const gapNames = gaps.map(g => g.member_name)
    expect(gapNames).toContain('Bob')
    expect(gapNames).toContain('Dave')
    expect(gapNames).not.toContain('Alice')
    expect(gapNames).not.toContain('Charlie')

    const daveGap = gaps.find(g => g.member_name === 'Dave')
    expect(daveGap?.next_up_items.length).toBe(1)
    expect(daveGap?.next_up_items[0].id).toBe(107)
  })

  it('builds full standup summary and generates markdown digest', () => {
    const summary = buildStandupSummary(mockWorkItems, [
      { name: 'Alice' },
      { name: 'Bob' },
      { name: 'Charlie' },
      { name: 'Dave' }
    ])

    expect(summary.total_attention_count).toBe(3 + 1 + 2) // 3 blocked + 1 bottleneck + 2 gaps
    expect(summary.blocked_items.length).toBe(3)
    expect(summary.review_bottlenecks.length).toBe(1)
    expect(summary.workload_gaps.length).toBe(2)

    const digest = generateStandupDigest('CloudOps', 'Sprint 26-09', summary)
    expect(digest).toContain('## 🚀 Smart Standup: CloudOps (Sprint 26-09)')
    expect(digest).toContain('### 🚨 Blocked Work (3)')
    expect(digest).toContain('### ⏳ Review Bottlenecks (1)')
    expect(digest).toContain('### ⚠️ Workload Gaps (2)')
  })
})
