import type {
  AdoWorkItem,
  StandupBlockedItem,
  StandupReviewBottleneck,
  StandupWorkloadGap,
  StandupSummary
} from '../types/api'

export const CLOSED_STATES = ['closed', 'done', 'completed', 'resolved']
export const ACTIVE_IN_PROGRESS_STATES = ['in progress', 'active', 'doing']
export const TO_DO_STATES = ['to do', 'new', 'proposed', 'approved']

export function isClosed(state: string): boolean {
  return CLOSED_STATES.includes((state || '').trim().toLowerCase())
}

export function detectBlockedItems(workItems: AdoWorkItem[]): StandupBlockedItem[] {
  const blocked: StandupBlockedItem[] = []

  for (const item of workItems) {
    if (isClosed(item.state)) continue

    const stateLower = (item.state || '').toLowerCase()
    const tagsLower = (item.tags || '').toLowerCase()

    const isStateBlocked = stateLower === 'blocked'
    const isTagBlocked = tagsLower.includes('blocked') || tagsLower.includes('impediment')
    const isFieldBlocked = Boolean(item.is_blocked)

    if (isStateBlocked || isTagBlocked || isFieldBlocked) {
      let reason = 'Flagged as Blocked'
      if (isStateBlocked) reason = 'State: Blocked'
      else if (isTagBlocked) reason = tagsLower.includes('impediment') ? 'Tag: Impediment' : 'Tag: Blocked'

      blocked.push({
        id: item.id,
        title: item.title,
        work_item_type: item.work_item_type,
        state: item.state,
        assigned_to_name: item.assigned_to_name,
        assigned_to_avatar: item.assigned_to_avatar,
        web_url: item.web_url,
        reason,
        tags: item.tags,
        remaining_work: item.remaining_work,
        story_points: item.story_points,
        area_path: item.area_path,
        comments: null
      })
    }
  }

  // Sort by ID ascending
  return blocked.sort((a, b) => a.id - b.id)
}

export function detectReviewBottlenecks(workItems: AdoWorkItem[]): StandupReviewBottleneck[] {
  const bottlenecks: StandupReviewBottleneck[] = []

  for (const item of workItems) {
    if (isClosed(item.state)) continue

    const stateLower = (item.state || '').toLowerCase()
    const isInReviewState = ['in review', 'review', 'ready for review'].includes(stateLower)
    const isStale = Boolean(item.is_stale_in_review)
    const daysInReview = item.business_days_in_review ?? 0

    if (isInReviewState || isStale || daysInReview >= 1) {
      bottlenecks.push({
        id: item.id,
        title: item.title,
        work_item_type: item.work_item_type,
        state: item.state,
        assigned_to_name: item.assigned_to_name,
        assigned_to_avatar: item.assigned_to_avatar,
        web_url: item.web_url,
        business_days_in_review: Math.max(1, daysInReview),
        remaining_work: item.remaining_work,
        story_points: item.story_points,
        area_path: item.area_path
      })
    }
  }

  // Sort by business days in review descending (longest in review first)
  return bottlenecks.sort((a, b) => b.business_days_in_review - a.business_days_in_review)
}

export function detectWorkloadGaps(
  workItems: AdoWorkItem[],
  members: Array<{ name: string; avatar?: string | null; capacity_per_day?: number }>
): StandupWorkloadGap[] {
  const gaps: StandupWorkloadGap[] = []

  // Ensure unique members list
  const memberMap = new Map<string, { name: string; avatar?: string | null; capacity_per_day?: number }>()
  for (const m of members) {
    const cleanName = (m.name || '').trim()
    if (!cleanName || cleanName.toLowerCase() === 'unassigned') continue
    if (!memberMap.has(cleanName.toLowerCase())) {
      memberMap.set(cleanName.toLowerCase(), m)
    }
  }

  // Also include any assignees from work items not in capacity members
  for (const item of workItems) {
    const cleanName = (item.assigned_to_name || '').trim()
    if (!cleanName || cleanName.toLowerCase() === 'unassigned') continue
    if (!memberMap.has(cleanName.toLowerCase())) {
      memberMap.set(cleanName.toLowerCase(), {
        name: cleanName,
        avatar: item.assigned_to_avatar
      })
    }
  }

  for (const [, member] of memberMap.entries()) {
    const memberItems = workItems.filter(
      w => (w.assigned_to_name || '').trim().toLowerCase() === member.name.toLowerCase()
    )

    const openItems = memberItems.filter(w => !isClosed(w.state))
    const inProgress = openItems.filter(w =>
      ACTIVE_IN_PROGRESS_STATES.includes((w.state || '').trim().toLowerCase())
    )
    const toDo = openItems.filter(w =>
      TO_DO_STATES.includes((w.state || '').trim().toLowerCase())
    )

    if (inProgress.length === 0) {
      gaps.push({
        member_name: member.name,
        avatar: member.avatar,
        capacity_per_day: member.capacity_per_day,
        in_progress_count: 0,
        to_do_count: toDo.length,
        next_up_items: toDo.slice(0, 4).map(w => ({
          id: w.id,
          title: w.title,
          work_item_type: w.work_item_type,
          web_url: w.web_url
        }))
      })
    }
  }

  // Sort by member name
  return gaps.sort((a, b) => a.member_name.localeCompare(b.member_name))
}

export function buildStandupSummary(
  workItems: AdoWorkItem[],
  members: Array<{ name: string; avatar?: string | null; capacity_per_day?: number }> = []
): StandupSummary {
  const blocked_items = detectBlockedItems(workItems)
  const review_bottlenecks = detectReviewBottlenecks(workItems)
  const workload_gaps = detectWorkloadGaps(workItems, members)

  const total_attention_count = blocked_items.length + review_bottlenecks.length + workload_gaps.length

  return {
    total_attention_count,
    blocked_items,
    review_bottlenecks,
    workload_gaps
  }
}

export function generateStandupDigest(
  teamName: string,
  sprintName: string,
  summary: StandupSummary
): string {
  const dateStr = new Date().toLocaleDateString(undefined, {
    weekday: 'short',
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  })

  let digest = `## 🚀 Smart Standup: ${teamName} (${sprintName})\n`
  digest += `**Date:** ${dateStr} · **Attention Items:** ${summary.total_attention_count}\n\n`

  // 1. Blocked
  digest += `### 🚨 Blocked Work (${summary.blocked_items.length})\n`
  if (summary.blocked_items.length === 0) {
    digest += `- *No blocked items today! Team is clear to proceed.*\n\n`
  } else {
    for (const b of summary.blocked_items) {
      const who = b.assigned_to_name ? `@${b.assigned_to_name}` : 'Unassigned'
      const pts = b.story_points ? ` (${b.story_points} pts)` : ''
      digest += `- **#${b.id}** [${b.work_item_type}] ${b.title} · ${who}${pts} — *${b.reason}*\n`
    }
    digest += `\n`
  }

  // 2. Review Bottlenecks
  digest += `### ⏳ Review Bottlenecks (${summary.review_bottlenecks.length})\n`
  if (summary.review_bottlenecks.length === 0) {
    digest += `- *No stale reviews! Code reviews are flowing smoothly.*\n\n`
  } else {
    for (const r of summary.review_bottlenecks) {
      const who = r.assigned_to_name ? `@${r.assigned_to_name}` : 'Unassigned'
      const days = r.business_days_in_review === 1 ? '1 business day' : `${r.business_days_in_review} business days`
      digest += `- **#${r.id}** [${r.work_item_type}] ${r.title} · ${who} — *In review for ${days}*\n`
    }
    digest += `\n`
  }

  // 3. Workload Gaps
  digest += `### ⚠️ Workload Gaps (${summary.workload_gaps.length})\n`
  if (summary.workload_gaps.length === 0) {
    digest += `- *All team members have active work in progress today.*\n\n`
  } else {
    for (const g of summary.workload_gaps) {
      const nextCount = g.to_do_count > 0 ? `${g.to_do_count} to-do items ready` : 'No queued tasks'
      digest += `- **@${g.member_name}**: 0 active tasks in progress today (${nextCount})\n`
      if (g.next_up_items.length > 0) {
        for (const item of g.next_up_items) {
          digest += `  - Next up: #${item.id} [${item.work_item_type}] ${item.title}\n`
        }
      }
    }
    digest += `\n`
  }

  digest += `*Generated automatically via ADO Pipeline Insight Smart Standup Hub.*`
  return digest
}
