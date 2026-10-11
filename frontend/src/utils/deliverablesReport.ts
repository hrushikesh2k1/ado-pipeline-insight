import type {
  AdoSprintBoardResponse,
  AdoWorkItem,
  AdoMilestoneItem
} from '../types/api'
import type {
  DeliverablesReport,
  PendingDeliverableItem,
  MemberContributionItem,
  DeliverablesStreamSummary,
  DeliverablesReportStatus
} from '../types/deliverables'

const memoryReportCache = new Map<string, DeliverablesReport>()

export function getDeliverablesStorageKey(
  org: string,
  project: string,
  teamId: string,
  iterationId?: string
): string {
  const o = (org || '').toLowerCase()
  const p = (project || '').toLowerCase()
  const t = (teamId || '').toLowerCase()
  const i = (iterationId || '').toLowerCase()
  return `ado_deliverables_report_${o}:${p}:${t}:${i}`
}

export function formatReportDate(isoString: string): string {
  if (!isoString) return 'recently'
  try {
    const d = new Date(isoString)
    if (isNaN(d.getTime())) return 'recently'
    return d.toLocaleString('en-GB', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true
    })
  } catch {
    return 'recently'
  }
}

export function loadSavedDeliverablesReport(
  org: string,
  project: string,
  teamId: string,
  iterationId?: string
): DeliverablesReport | null {
  if (!org || !project || !teamId) return null
  const key = getDeliverablesStorageKey(org, project, teamId, iterationId)
  if (memoryReportCache.has(key)) {
    return memoryReportCache.get(key)!
  }
  try {
    const raw = localStorage.getItem(key)
    if (raw) {
      const parsed = JSON.parse(raw) as DeliverablesReport
      memoryReportCache.set(key, parsed)
      return parsed
    }
  } catch {}
  return null
}

export function saveDeliverablesReportToStorage(report: DeliverablesReport): void {
  if (!report || !report.organization || !report.project || !report.teamId) return
  const key = getDeliverablesStorageKey(
    report.organization,
    report.project,
    report.teamId,
    report.iterationId
  )
  memoryReportCache.set(key, report)
  try {
    localStorage.setItem(key, JSON.stringify(report))
  } catch (err) {
    console.warn('Failed to persist deliverables report to localStorage:', err)
  }
}

export function isItemClosedInSprint(
  item: {
    state: string
    closed_date?: string | null
    state_change_date?: string | null
    changed_date?: string | null
    completed_date?: string | null
  },
  iteration?: {
    start_date?: string | null
    finish_date?: string | null
  } | null
): boolean {
  const closedStates = ['closed', 'done', 'completed', 'resolved']
  if (!closedStates.includes((item.state || '').toLowerCase())) return false
  if (!iteration?.start_date || !iteration?.finish_date) return true

  const start = new Date(iteration.start_date).getTime()
  const finish = new Date(iteration.finish_date)
  finish.setUTCHours(23, 59, 59, 999)
  const finishTime = finish.getTime()

  const closedRaw = item.closed_date || item.completed_date || item.state_change_date || item.changed_date
  if (!closedRaw) return true
  const closedTime = new Date(closedRaw).getTime()
  if (isNaN(closedTime)) return true

  return closedTime >= start && closedTime <= finishTime
}

export function buildDeliverablesReport(
  boardData: AdoSprintBoardResponse,
  organization: string,
  project: string,
  teamId: string,
  iterationId: string,
  sprintName: string,
  status: DeliverablesReportStatus = 'fresh',
  existingReport?: DeliverablesReport | null,
  error?: string
): DeliverablesReport {
  const closedStates = ['closed', 'done', 'completed', 'resolved']
  const storyTypes = ['user story', 'product backlog item', 'requirement', 'feature', 'story', 'bug']

  // Map tasks by parent
  const tasksByParent: Record<number, AdoWorkItem[]> = {}
  boardData.work_items.forEach(w => {
    if (w.work_item_type.toLowerCase() === 'task' && w.parent_id) {
      if (!tasksByParent[w.parent_id]) tasksByParent[w.parent_id] = []
      tasksByParent[w.parent_id].push(w)
    }
  })

  // Customer-facing story/bug items
  const storyItems = boardData.work_items.filter(w =>
    storyTypes.includes(w.work_item_type.toLowerCase())
  )

  // 1. Completed Deliverables - stories closed in the sprint
  let completedDeliverables: AdoMilestoneItem[] = []
  if (boardData.milestone?.achieved_items && boardData.milestone.achieved_items.length > 0) {
    completedDeliverables = boardData.milestone.achieved_items.filter(item =>
      isItemClosedInSprint(item, boardData.iteration)
    )
  } else {
    completedDeliverables = storyItems
      .filter(s => isItemClosedInSprint(s, boardData.iteration))
      .map(story => {
        const typeLower = story.work_item_type.toLowerCase()
        const isBug = typeLower === 'bug'
        const category = isBug ? 'Bug Fix & Quality' : 'Feature & Business Value'
        const areaLeaf = story.area_path ? story.area_path.split('\\').pop()?.trim() : ''
        const milestoneStream = areaLeaf || 'General Delivery'

        const children = tasksByParent[story.id] || []
        const childClosed = children.filter(c => closedStates.includes(c.state.toLowerCase())).length
        const storyHours = story.completed_work || 0
        const childrenHours = children.reduce((acc, c) => acc + (c.completed_work || 0), 0)
        const itemHours = Math.round((storyHours + childrenHours) * 10) / 10

        return {
          id: story.id,
          title: story.title,
          work_item_type: story.work_item_type,
          state: story.state,
          assigned_to_name: story.assigned_to_name,
          assigned_to_avatar: story.assigned_to_avatar,
          completed_date: story.state_change_date || story.changed_date,
          web_url: story.web_url,
          category,
          milestone_stream: milestoneStream,
          hours_delivered: itemHours,
          child_tasks_total: children.length,
          child_tasks_closed: childClosed,
          description: story.description,
          acceptance_criteria: story.acceptance_criteria,
          issue_summary: story.description || `No description recorded on this ${typeLower}.`,
          achievement_summary: story.acceptance_criteria
            ? `Acceptance criteria met: ${story.acceptance_criteria}`
            : `Marked ${story.state} with definition-of-done criteria satisfied.`
        }
      })
  }

  // 2. Pending & In-Progress Items
  const pendingItemsRaw = storyItems.filter(
    s => !closedStates.includes(s.state.toLowerCase())
  )
  const pendingDeliverables: PendingDeliverableItem[] = pendingItemsRaw.map(s => {
    const children = tasksByParent[s.id] || []
    const childClosed = children.filter(c => closedStates.includes(c.state.toLowerCase())).length
    const childrenRem = children.reduce((acc, c) => acc + (c.remaining_work || 0), 0)
    const totalRem = Math.round(((s.remaining_work || 0) + childrenRem) * 10) / 10

    return {
      id: s.id,
      title: s.title,
      work_item_type: s.work_item_type,
      state: s.state,
      assigned_to_name: s.assigned_to_name || undefined,
      assigned_to_avatar: s.assigned_to_avatar || undefined,
      web_url: s.web_url || undefined,
      remaining_work: totalRem,
      story_points: s.story_points ?? undefined,
      child_tasks_total: children.length,
      child_tasks_closed: childClosed
    }
  })

  // 3. Team Member Contributions
  const memberMap: Record<string, MemberContributionItem> = {}
  boardData.work_items.forEach(w => {
    const name = w.assigned_to_name || 'Unassigned'
    if (!memberMap[name]) {
      memberMap[name] = {
        name,
        avatar: w.assigned_to_avatar || undefined,
        completedCount: 0,
        pendingCount: 0,
        completedHours: 0,
        totalHours: 0
      }
    }
    const isClosed = closedStates.includes(w.state.toLowerCase())
    const hours = (w.completed_work || 0) + (w.remaining_work || 0)
    if (storyTypes.includes(w.work_item_type.toLowerCase())) {
      if (isClosed) {
        memberMap[name].completedCount += 1
      } else {
        memberMap[name].pendingCount += 1
      }
    }
    memberMap[name].completedHours += w.completed_work || 0
    memberMap[name].totalHours += hours
  })

  const memberContributions = Object.values(memberMap)
    .map(m => ({
      ...m,
      completedHours: Math.round(m.completedHours * 10) / 10,
      totalHours: Math.round(m.totalHours * 10) / 10
    }))
    .sort((a, b) => b.completedCount - a.completedCount || b.completedHours - a.completedHours)

  // 4. Capacity & Effort Summary
  const totalStories = storyItems.length
  const closedStoriesCount = completedDeliverables.length
  const pendingStoriesCount = pendingDeliverables.length
  const completionRatePct =
    totalStories > 0 ? Math.round((closedStoriesCount / totalStories) * 1000) / 10 : 0
  const totalDeliveredHours =
    boardData.milestone?.total_delivered_hours ??
    Math.round(completedDeliverables.reduce((acc, c) => acc + c.hours_delivered, 0) * 10) / 10

  const featuresDeliveredCount = completedDeliverables.filter(
    c => !c.work_item_type.toLowerCase().includes('bug')
  ).length
  const bugsResolvedCount = completedDeliverables.filter(c =>
    c.work_item_type.toLowerCase().includes('bug')
  ).length

  const streams: DeliverablesStreamSummary[] =
    boardData.milestone?.graph_data?.streams.map(s => ({
      name: s.name,
      totalCount: s.total_count,
      closedCount: s.closed_count,
      deliveredHours: s.delivered_hours,
      completionPct: s.completion_pct
    })) || []

  // 5. Warnings & Hygiene
  const unassignedItems = storyItems
    .filter(s => !s.assigned_to_name)
    .map(s => ({ id: s.id, title: s.title, type: s.work_item_type }))

  const closedWithoutHoursItems = boardData.work_items
    .filter(w => w.is_closed_without_hours)
    .map(w => ({ id: w.id, title: w.title, assignee: w.assigned_to_name || undefined }))

  const staleInReviewItems = boardData.work_items
    .filter(w => w.is_stale_in_review)
    .map(w => ({
      id: w.id,
      title: w.title,
      assignee: w.assigned_to_name || undefined,
      days: w.business_days_in_review || 4
    }))

  const warningsAndHygiene = {
    closedWithoutHoursCount: boardData.checks_summary?.tasks_closed_without_hours_count || closedWithoutHoursItems.length,
    staleInReviewCount: boardData.checks_summary?.stories_in_review_stale_count || staleInReviewItems.length,
    missingOwnersCount: unassignedItems.length,
    unassignedItems,
    closedWithoutHoursItems,
    staleInReviewItems
  }

  return {
    id: `${organization}:${project}:${teamId}:${iterationId}`,
    organization,
    project,
    teamId,
    iterationId,
    sprintName,
    generatedAt: existingReport && status === 'saved' ? existingReport.generatedAt : new Date().toISOString(),
    status,
    lastRegenerateError: error,
    completedDeliverables,
    pendingDeliverables,
    memberContributions,
    capacityEffortSummary: {
      totalStories,
      closedStoriesCount,
      pendingStoriesCount,
      completionRatePct,
      totalDeliveredHours,
      featuresDeliveredCount,
      bugsResolvedCount,
      streams
    },
    warningsAndHygiene,
    aiSummary: existingReport?.aiSummary || null
  }
}
