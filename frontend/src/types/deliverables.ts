import type { AdoMilestoneItem, MilestoneAiSummaryResponse } from './api'

export type DeliverablesReportStatus = 'saved' | 'fresh' | 'regenerate_failed'

export interface PendingDeliverableItem {
  id: number
  title: string
  work_item_type: string
  state: string
  assigned_to_name?: string
  assigned_to_avatar?: string
  web_url?: string
  remaining_work?: number
  story_points?: number
  child_tasks_total: number
  child_tasks_closed: number
}

export interface MemberContributionItem {
  name: string
  avatar?: string
  completedCount: number
  pendingCount: number
  completedHours: number
  totalHours: number
}

export interface DeliverablesStreamSummary {
  name: string
  totalCount: number
  closedCount: number
  deliveredHours: number
  completionPct: number
}

export interface DeliverablesCapacitySummary {
  totalStories: number
  closedStoriesCount: number
  pendingStoriesCount: number
  completionRatePct: number
  totalDeliveredHours: number
  featuresDeliveredCount: number
  bugsResolvedCount: number
  streams: DeliverablesStreamSummary[]
}

export interface DeliverablesWarningsSummary {
  closedWithoutHoursCount: number
  staleInReviewCount: number
  missingOwnersCount: number
  unassignedItems: { id: number; title: string; type: string }[]
  closedWithoutHoursItems: { id: number; title: string; assignee?: string }[]
  staleInReviewItems: { id: number; title: string; assignee?: string; days: number }[]
}

export interface DeliverablesReport {
  id: string
  organization: string
  project: string
  teamId: string
  iterationId: string
  sprintName: string
  generatedAt: string
  status: DeliverablesReportStatus
  lastRegenerateError?: string
  completedDeliverables: AdoMilestoneItem[]
  pendingDeliverables: PendingDeliverableItem[]
  memberContributions: MemberContributionItem[]
  capacityEffortSummary: DeliverablesCapacitySummary
  warningsAndHygiene: DeliverablesWarningsSummary
  aiSummary?: MilestoneAiSummaryResponse | null
}
